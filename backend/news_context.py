"""On-demand source reading; never publishes or changes pending permissions."""
import asyncio
import hashlib
import json
import time

from . import news, news_policy, reading, review_capture
from .publisher_fetch import Publisher, checked_url
from .bailian import AIError

# Every registered source has a status, including collectors without a body parser.
# This policy covers transient AI context only, not public republication or RAG import.
POLICY_VERSION = 'news-context-20261008-v1'
SUPPORTED = {'nasa', 'cnsa', 'cmse', 'cas_space', 'landspace'}
SOURCE_REGISTRY = {
    source: {'status': 'supported' if source in SUPPORTED else 'unsupported',
             'basis': '用户要求按已登记新闻链接补读原文，用于单篇科普与提问；遵守 robots 和来源范围。',
             'purpose': 'session_ai_read', 'cache_seconds': 21600,
             'parser': 'review_capture.strict' if source in SUPPORTED else None}
    for source in news.SOURCES
}


def snapshot(article_id):
    with news.connect() as db:
        row = db.execute('SELECT a.*,s.enabled AS source_enabled FROM articles a '
                         'JOIN sources s ON s.id=a.source_id WHERE a.id=?', (article_id,)).fetchone()
        if row is None or news_policy.excluded_item(row):
            raise AIError('article_unavailable', 404)
        item = dict(row)
        edition = reading.editions(db, [article_id]).get(article_id)
    document = json.loads(edition['document']) if edition else None
    policy = SOURCE_REGISTRY.get(item['source_id'], {'status': 'unsupported'})
    marker = [item['content_hash'], item['title'], item['original_url'], item['source_enabled'],
              edition['version'] if edition else None, edition['revision'] if edition else None,
              edition['withdrawn'] if edition else None, POLICY_VERSION, policy]
    fingerprint = hashlib.sha256(json.dumps(marker, sort_keys=True).encode()).hexdigest()
    status = 'pending'
    if not item['source_enabled'] or edition and edition['withdrawn']:
        status = 'withdrawn'
    elif document and document['permissions']['ai_context']['status'] in {'denied', 'withdrawn'}:
        status = 'blocked'
    elif document and document['permissions']['ai_context'].get('expires_at'):
        permission = document['permissions']['ai_context']
        from datetime import datetime, timezone
        if datetime.fromisoformat(permission['expires_at']) <= datetime.now(timezone.utc):
            status = 'blocked'
    if status == 'pending' and policy['status'] != 'supported':
        status = 'unsupported'
    return item, document, fingerprint, status


def response(item, fingerprint, status, document=None, warning=None):
    blocks = []
    if document:
        blocks = [{**block, 'block_id': f'b{index:04d}'} for index, block in enumerate(document['blocks'], 1)]
    content_version = hashlib.sha256(json.dumps([fingerprint, blocks], sort_keys=True, ensure_ascii=False).encode()).hexdigest() if blocks else fingerprint
    return {'article_id': item['id'], 'title': item['title'], 'source_id': item['source_id'],
            'original_url': item['original_url'], 'published_at': item['published_at'],
            'fetched_at': news.now(), 'content_version': content_version, 'record_version': fingerprint, 'read_status': status,
            'completeness': 'structure_checked' if status == 'full' else 'incomplete',
            'language': document['language'] if document else item['lang'], 'blocks': blocks,
            'total_blocks': len(blocks), 'read_range': [1, len(blocks)] if blocks else [],
            'source_sha256': document.get('source_sha256') if document else None,
            'policy_version': POLICY_VERSION, 'warnings': [warning] if warning else []}


class ContextService:
    def __init__(self, store, enabled=False, timeout=25):
        self.store, self.enabled, self.timeout = store, enabled, timeout
        self.tasks = {}

    def status(self, article_id):
        item, document, fingerprint, status = snapshot(article_id)
        if not self.enabled:
            status = 'blocked'
        return response(item, fingerprint, status)

    def cached(self, article_id, fingerprint):
        with self.store.connection() as db:
            row = db.execute('SELECT document FROM news_contexts WHERE article_id=? AND fingerprint=? '
                             'AND expires>?', (article_id, fingerprint, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    async def read(self, article_id):
        item, document, fingerprint, status = snapshot(article_id)
        if not self.enabled:
            status = 'blocked'
        if status != 'pending':
            return response(item, fingerprint, status)
        cached = self.cached(article_id, fingerprint)
        if cached:
            return cached
        key = (article_id, fingerprint)
        if key not in self.tasks:
            if len(self.tasks) >= 4:
                return response(item, fingerprint, 'pending', warning='原文读取任务较多，请稍后重试。')
            # A timed-out caller leaves the bounded worker alive and deduplicated.
            task = asyncio.create_task(asyncio.to_thread(self.fetch, item, document, fingerprint))
            self.tasks[key] = task
            task.add_done_callback(lambda finished: self.tasks.pop(key, None))
        try:
            return await asyncio.wait_for(asyncio.shield(self.tasks[key]), self.timeout)
        except asyncio.TimeoutError:
            return response(item, fingerprint, 'pending', warning='原文读取仍在进行，请稍后重试。')

    def fetch(self, item, document, fingerprint):
        try:
            checked_url(item['source_id'], item['original_url'])
            if document and document['mode'] == 'full' and document['completeness'] in {'complete_checked', 'structure_checked'}:
                result = response(item, fingerprint, 'full', document)
            else:
                client = Publisher(item['source_id'])
                client.deadline = time.monotonic() + 20
                raw, mime = client.get(item['original_url'])
                if mime not in {'text/html', 'application/xhtml+xml'}:
                    result = response(item, fingerprint, 'unsupported', warning='目前仅支持静态 HTML 正文。')
                else:
                    try:
                        doc, _ = review_capture.parse(item['source_id'], item['original_url'], raw, 'news-agent', strict=True)
                        if doc['language'] == 'und':
                            doc['language'] = item['lang']
                        reading.validate(doc)
                        result = response(item, fingerprint, 'full', doc)
                    except ValueError:
                        doc, _ = review_capture.parse(item['source_id'], item['original_url'], raw, 'news-agent')
                        if doc['language'] == 'und':
                            doc['language'] = item['lang']
                        reading.validate(doc)
                        result = response(item, fingerprint, 'partial', doc, '正文结构未完整覆盖，不能据此声称读过全文。')
            # Bound context without silently truncating its version or blocks.
            if len(json.dumps(result, ensure_ascii=False).encode()) > 80000 or len(result['blocks']) > 250:
                result = response(item, fingerprint, 'unsupported', warning='正文超过首期上下文上限，需分段适配。')
        except ValueError as error:
            if str(error) == 'Unreviewed NASA path':
                result = response(item, fingerprint, 'unsupported', warning='该 NASA 栏目路径暂未适配。')
            else:
                result = response(item, fingerprint, 'unavailable', warning='来源正文暂不可读取；不绕过访问限制。')
        except (OSError, UnicodeError, KeyError):
            result = response(item, fingerprint, 'unavailable', warning='来源正文暂不可读取；不绕过访问限制。')
        _, _, current, status = snapshot(item['id'])
        if current != fingerprint or status != 'pending':
            return response(item, current, 'withdrawn', warning='原文或使用策略已变化。')
        ttl = SOURCE_REGISTRY[item['source_id']]['cache_seconds'] if result['read_status'] == 'full' else 120
        with self.store.connection() as db:
            db.execute('INSERT OR REPLACE INTO news_contexts VALUES(?,?,?,?)',
                       (item['id'], fingerprint, json.dumps(result, ensure_ascii=False), time.time() + ttl))
        return result

    async def close(self):
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
