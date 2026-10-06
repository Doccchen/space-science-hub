"""Server-local history, reading and resource checks; no publisher/OSS requests.

before runs via stdin in the previous image. Other modes use the new image.
"""
import json
import os
import sqlite3
import sys
import urllib.request
from contextlib import closing
from pathlib import Path

DB = Path(os.environ.get('NEWS_DB_PATH', '/data/news.sqlite3'))
EVIDENCE = DB.parent/'reading-acceptance'
BASE = 'http://127.0.0.1:8000'


def snapshot():
    with closing(sqlite3.connect(DB)) as conn:
        conn.row_factory = sqlite3.Row
        return {'articles': [dict(row) for row in conn.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id')],
                'queues': {table: [dict(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                           for table in ('backfill_runs', 'backfill_items')},
                'sources': [dict(row) for row in conn.execute('SELECT id,enabled FROM sources ORDER BY id')]}


def api(path):
    with urllib.request.urlopen(BASE+path, timeout=10) as response:
        return json.load(response), response.headers


def check():
    from backend import news, reading
    from tools.accept_resources import check_resources
    before = json.loads((EVIDENCE/'before.json').read_text(encoding='utf-8'))
    after = snapshot()
    current = {item['id']: item for item in after['articles']}
    assert all(current.get(item['id']) == item for item in before['articles']), 'Historical identities changed'
    assert after['queues'] == before['queues'], 'Historical queues changed'
    assert after['sources'] == before['sources'], 'Source enabled flags changed'
    samples = []
    with news.connect() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 5
        for file in sorted(Path('/app/content/reading').glob('*.json')):
            document = json.loads(file.read_text(encoding='utf-8'))
            if document['mode'] != 'full':
                continue
            row = conn.execute('SELECT id,lang,source_id,original_url FROM articles WHERE canonical_url=?', (news.canonical_url(document['original_url']),)).fetchone()
            if row is None:
                samples.append({'file': file.name, 'status': 'article_missing'}); continue
            expected = reading.content_with_assets(conn, dict(row), reading.editions(conn, [row['id']]).get(row['id']))
            content, headers = api(f"/api/news/{row['id']}/content")
            assert headers.get('Cache-Control') == 'no-store'
            assert content == expected, 'Public scope differs from current permission'
            assert 'permissions' not in content and 'reviewer' not in content
            metadata, headers = api(f"/api/news/{row['id']}")
            assert metadata['read_scope'] == expected['read_scope']
            assert headers.get('Cache-Control') == 'no-store'
            assert metadata['summary'] == '' if expected['read_scope'] != 'full_text' else metadata['summary_kind'] in {'reviewed_excerpt', 'body_excerpt'}
            samples.append({'article_id': row['id'], 'scope': expected['read_scope'], 'version': expected['content_version'], 'blocks': len(content['blocks'])})
    listing, headers = api('/api/news?limit=2')
    assert listing['items'] and headers.get('Cache-Control') == 'no-store'
    resources = check_resources()
    from backend.reading_policy import SOURCE_READING_POLICY
    link_checks = []
    for source, policy in SOURCE_READING_POLICY.items():
        if policy != 'link_only':
            continue
        listing, _ = api('/api/news?source='+source+'&limit=2')
        for item in listing['items']:
            metadata, _ = api(f"/api/news/{item['id']}")
            content, _ = api(f"/api/news/{item['id']}/content")
            assert item['summary'] == metadata['summary'] == ''
            assert item['reading_mode'] == metadata['reading_mode'] == content['reading_mode'] == 'link_only'
            assert content['blocks'] == content['assets'] == [] and content['original_url'] == item['original_url']
        link_checks.append({'source': source, 'checked': len(listing['items'])})
    full_count = sum(item.get('scope') == 'full_text' for item in samples)
    sample_acceptance = 'passed' if full_count >= 3 else 'incomplete'
    return {'health': api('/api/health')[0], 'history_and_queues': 'passed', 'samples': samples,
            'sample_acceptance': sample_acceptance, 'sample_counts': {'full_text': full_count}, 'link_only_checks': link_checks,
            'resources': resources, 'images': 'deferred_by_user', 'ai': 'excluded',
            'browser_interaction': 'requires domestic user verification'}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1]
    if mode == 'before':
        (EVIDENCE/'before.json').write_text(json.dumps(snapshot()), encoding='utf-8')
        with closing(sqlite3.connect(DB)) as origin, closing(sqlite3.connect(EVIDENCE/'before.sqlite3')) as target:
            origin.backup(target)
        print('Consistent database backup and history snapshot saved')
    elif mode == 'capture':
        with closing(sqlite3.connect(DB)) as conn:
            rows = conn.execute('SELECT article_id,version,revision,withdrawn FROM reading_heads ORDER BY article_id').fetchall()
        (EVIDENCE/'editions.json').write_text(json.dumps(rows), encoding='utf-8')
        print('Reading editions saved before container recreation')
    elif mode == 'after':
        result = check()
        if (EVIDENCE/'editions.json').exists():
            with closing(sqlite3.connect(DB)) as conn:
                rows = conn.execute('SELECT article_id,version,revision,withdrawn FROM reading_heads ORDER BY article_id').fetchall()
            baseline = json.loads((EVIDENCE/'editions.json').read_text())
            current = {row[0]: list(row) for row in rows}
            with closing(sqlite3.connect(DB)) as conn:
                for row in baseline:
                    assert row[0] in current, 'Reading edition lost on recreation'
                    old_document = conn.execute('SELECT document FROM article_contents WHERE article_id=? AND version=?', (row[0], row[1])).fetchone()
                    assert old_document, 'Immutable old edition lost'
                    if current[row[0]] != row:
                        old = json.loads(old_document[0])
                        new = conn.execute('SELECT document FROM article_contents WHERE article_id=? AND version=?', (row[0], current[row[0]][1])).fetchone()
                        assert new and json.loads(new[0]).get('publication_mode') == 'government_direct', 'Unexpected edition change'
                        assert row[3] == current[row[0]][3] == 0, 'Withdrawal changed'
                        assert old['permissions']['text']['status'] == 'pending' or old['mode'] == 'guide', 'Reviewed full text unexpectedly replaced'
            result['container_recreation'] = 'passed'
        (EVIDENCE/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        raise ValueError('Unknown acceptance mode')


if __name__ == '__main__':
    main()
