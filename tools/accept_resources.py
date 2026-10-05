"""Server-local resource and history checks; never connects to OSS.

before works in the old image via stdin; after works in the upgraded image.
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(os.environ.get('NEWS_DB_PATH', '/data/news.sqlite3'))
EVIDENCE = DB.parent / 'resource-acceptance'
BASE = 'http://127.0.0.1:8000'


def snapshot():
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return {
            'articles': [dict(row) for row in conn.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id')],
            'queues': {table:[dict(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                       for table in ('backfill_runs', 'backfill_items')},
            'sources': [dict(row) for row in conn.execute('SELECT id,enabled FROM sources ORDER BY id')],
        }


def api(path):
    with urllib.request.urlopen(BASE+path, timeout=10) as response:
        return json.load(response)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_resources():
    from backend import resources
    resources.catalog.load()
    expected = resources.catalog.public_items()
    assert len(expected) == 28, 'Expected 28 published resources'
    assert all(not item.description and not item.description_short for item in expected)
    ids, covers, redirects = [], 0, 0
    opener = urllib.request.build_opener(NoRedirect())
    for page in range(1, 4):
        data = api(f'/api/resources?page={page}')
        assert data['total'] == 28 and data['pages'] == 3
        assert len(data['items']) == (12 if page < 3 else 4)
        for item in data['items']:
            ids.append(item['id'])
            assert not item['description_short']
            if item['cover_url']:
                assert item['cover_url'].startswith('/assets/resource-covers/')
                with urllib.request.urlopen(BASE+item['cover_url'], timeout=10) as response:
                    assert response.status == 200 and response.headers.get_content_type() == 'image/jpeg'
                    assert 0 < len(response.read()) <= 120*1024
                covers += 1
            try:
                opener.open(BASE+item['download_url'], timeout=10)
                raise AssertionError('Download must redirect')
            except urllib.error.HTTPError as response:
                assert response.code == 302
                expected_item = next(value for value in expected if value.id == item['id'])
                assert response.headers['Location'] == resources.object_url(expected_item.object_key)
                assert response.headers['Cache-Control'] == 'no-store'
                response.close()
                redirects += 1
    assert ids == [item.id for item in expected] and len(set(ids)) == 28
    assert covers == 24 and redirects == 28
    assert api('/api/resources?q='+urllib.parse.quote('数值分析'))['total'] == 1
    assert api('/api/resources?q=not-a-book-20261005')['total'] == 0
    assert api('/api/resources?category='+urllib.parse.quote('数学与力学'))['total'] > 0
    assert api('/api/health')['status'] == 'ok'
    assert api('/api/news?limit=2')['items'], 'Historical news must remain readable'
    html = urllib.request.urlopen(BASE+'/', timeout=10).read().decode('utf-8')
    script = urllib.request.urlopen(BASE+'/assets/resources-ui.js', timeout=10).read().decode('utf-8')
    assert 'resource-dialog' not in html and '内容介绍' not in script
    return {'published_resources':28, 'pages':3, 'local_covers':24, 'placeholders':4,
            'controlled_redirects':redirects, 'introductions':False,
            'oss_network_check':'waived_by_user; no remote requests made'}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1]
    if mode == 'before':
        baseline = snapshot()
        (EVIDENCE/'before.json').write_text(json.dumps(baseline), encoding='utf-8')
        with sqlite3.connect(DB) as source, sqlite3.connect(EVIDENCE/'before.sqlite3') as destination:
            source.backup(destination)
        print(json.dumps({'saved_articles':len(baseline['articles']), 'backup':str(EVIDENCE/'before.sqlite3')}))
    elif mode == 'after':
        before = json.loads((EVIDENCE/'before.json').read_text(encoding='utf-8'))
        after = snapshot()
        current = {row['id']:row for row in after['articles']}
        assert all(current.get(row['id']) == row for row in before['articles']), 'Old article identities changed'
        assert before['queues'] == after['queues'], 'Historical queues changed'
        flags = {row['id']:row['enabled'] for row in after['sources']}
        assert all(flags.get(row['id']) == row['enabled'] for row in before['sources']), 'News source enable flags changed'
        result = check_resources()
        result.update(old_article_identities='passed', historical_queues='passed', news_source_flags='passed',
                      baseline_articles=len(before['articles']), current_articles=len(after['articles']))
        (EVIDENCE/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    else:
        raise ValueError('Usage: accept_resources before|after')


if __name__ == '__main__':
    main()
