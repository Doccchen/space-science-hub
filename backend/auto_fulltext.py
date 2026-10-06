"""Budgeted government text publication under the operator's display policy.

This is not a copyright audit or a grant from a publisher. Images stay separate.
"""
import asyncio
import json
import hashlib
import time
from . import news, reading, review_store, review_capture, review_worker
from .locking import operation_lock
from .reading_policy import direct_enabled, source_policy


def seed(limit=5):
    if not direct_enabled():
        return 0
    added = 0
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        candidates = conn.execute('''SELECT a.*,d.revision AS draft_revision,h.withdrawn,h.version,c.document
          FROM articles a JOIN sources s ON s.id=a.source_id
          LEFT JOIN reading_heads h ON h.article_id=a.id
          LEFT JOIN article_contents c ON c.article_id=h.article_id AND c.version=h.version
          LEFT JOIN review_drafts d ON d.article_id=a.id
          WHERE s.enabled=1 AND a.source_id IN ('nasa','cnsa','cmse')
          ORDER BY a.published_at DESC,a.id DESC''').fetchall()
        for item in candidates:
            if added >= limit or source_policy(item['source_id']) != 'government_candidate':
                continue
            if item['version']:
                document = json.loads(item['document'])
                if item['withdrawn'] or document['permissions']['text']['status'] in {'denied', 'withdrawn'}:
                    continue
                if document['mode'] == 'full':
                    if document['permissions']['text']['status'] in reading.ALLOWED:
                        continue
                    if document.get('publication_mode') == 'government_direct' and document.get('source_record_hash') == item['content_hash']:
                        continue
            jobs = conn.execute("SELECT state,created_at,payload FROM review_jobs WHERE article_id=? AND kind='auto_text' ORDER BY rowid DESC", (item['id'],)).fetchall()
            jobs = [row for row in jobs if json.loads(row['payload']).get('source_record_hash') == item['content_hash']]
            if any(row['state'] in {'queued', 'running', 'done'} for row in jobs):
                continue
            if len(jobs) >= 3:
                continue
            if jobs:
                from datetime import datetime
                if time.time()-datetime.fromisoformat(jobs[0]['created_at']).timestamp() < 86400:
                    continue
            payload = {'actor': 'government-auto', 'revision': item['draft_revision'] or 0, 'source_record_hash': item['content_hash']}
            try:
                review_worker.enqueue(conn, item['id'], 'auto_text', payload)
            except ValueError:
                break
            added += 1
    return added


def process(item, payload):
    if not direct_enabled() or source_policy(item['source_id']) != 'government_candidate':
        raise ValueError('Government automatic publication disabled')
    document, candidates = review_capture.capture(item, 'government-auto', strict=True)
    if item.get('content_source') and item['content_source'] not in document['credit']:
        document['credit'] += ' / 文章来源：' + item['content_source'][:500]
    document.update(publication_mode='government_direct', completeness='structure_checked',
                    source_record_hash=item['content_hash'],
                    notes='自动转载政府来源原始语言正文，保留发布方署名和原文入口；图片另行处理。')
    # Do not turn the operator's instruction into a fabricated text permission.
    document['permissions']['text'] = {'status': 'pending'}
    with operation_lock(news.DB_PATH, timeout=10), news.connect() as conn:
        if not direct_enabled():
            raise ValueError('Automatic publication disabled during capture')
        latest = review_store.article(conn, item['id'])
        if latest['content_hash'] != payload['source_record_hash']:
            raise ValueError('Collector metadata changed; waiting for a fresh capture')
        current = reading.editions(conn, [item['id']]).get(item['id'])
        if current:
            existing = json.loads(current['document'])
            protected_full = (existing['mode'] == 'full' and
                              (existing['permissions']['text']['status'] in reading.ALLOWED or
                               existing.get('publication_mode') == 'government_direct' and existing.get('source_record_hash') == item['content_hash']))
            if current['withdrawn'] or existing['permissions']['text']['status'] in {'denied', 'withdrawn'} or protected_full:
                raise ValueError('Existing edition or withdrawal retained')
        old_draft = conn.execute('SELECT document FROM review_drafts WHERE article_id=?', (item['id'],)).fetchone()
        if old_draft and json.loads(old_draft['document']).get('publication_mode') != 'government_direct':
            archived = reading.validate(json.loads(old_draft['document']))
            version = hashlib.sha256(archived.encode()).hexdigest()[:24]
            conn.execute('INSERT OR IGNORE INTO article_contents VALUES(?,?,?,?)', (item['id'], version, archived, news.now()))
            conn.execute('INSERT INTO reading_audit(article_id,version,action,reviewer,reason,created_at) VALUES(?,?,?,?,?,?)',
                         (item['id'], version, 'archive_unpublished_draft', 'government-auto', 'Previous private draft retained; not published', news.now()))
        revision = review_store.save_draft(item['id'], document, payload['revision'], 'government-auto', candidates, conn)
        document = json.loads(conn.execute('SELECT document FROM review_drafts WHERE article_id=?', (item['id'],)).fetchone()['document'])
        result = reading.publish(document, conn=conn)
        review_store.audit(conn, 'government-auto', item['id'], 'automatic_display', result['version'])
    return {**result, 'revision': revision}


async def loop():
    with news.connect() as conn:
        conn.execute("UPDATE review_jobs SET state='failed',result=? WHERE kind='auto_text' AND state='running'", (json.dumps({'error': 'Interrupted; retry after cooldown'}),))
    while True:
        if direct_enabled():
            try:
                await asyncio.to_thread(seed)
                await asyncio.to_thread(review_worker.run_one, ('auto_text',))
            except Exception:
                import logging
                logging.exception('Automatic government text task failed')
        await asyncio.sleep(60)
