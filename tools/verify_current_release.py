"""Verify runtime bytes, retained news identities and read-only public APIs; no model calls."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from urllib.request import urlopen

root=Path('/app')
manifest=json.loads(Path('/tmp/release-manifest.json').read_text())
for item in manifest['files']:
    if not item['path'].startswith(('backend/','web/','admin_web/','content/','tools/')):
        continue
    assert hashlib.sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256'], item['path']
base='http://127.0.0.1:8000'
for item in manifest['files']:
    if not item['path'].startswith('web/'):
        continue
    name=item['path'][4:]
    url=base+('/' if name=='index.html' else '/assets/'+name)
    with urlopen(url,timeout=15) as response:
        assert hashlib.sha256(response.read()).hexdigest()==item['sha256'], name
with sqlite3.connect('/tmp/news-before.sqlite3') as before, sqlite3.connect('/data/news.sqlite3') as after:
    prior=before.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles').fetchall()
    current=dict((row[0],row[1:]) for row in after.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles'))
    assert all(current.get(row[0])==row[1:] for row in prior), 'Historical identities changed'
    print('Retained historical articles:',len(prior),'current:',len(current))
for endpoint in ('/api/health','/api/news?page=1&page_size=10','/api/resources?page=1&page_size=12','/api/ai/status'):
    with urlopen(base+endpoint,timeout=15) as response:
        data=json.load(response)
    if endpoint.startswith('/api/news?'):
        assert data['page_size']==10 and len(data['items'])<=10
    print(endpoint,{key:data[key] for key in ('status','page','page_size','total','pages','total_pages','enabled') if key in data})
assert '<title>知航</title>' in (root/'web/index.html').read_text()
before_flags=json.loads(Path('/tmp/runtime-before.json').read_text())
assert all(os.environ.get(key)==value for key,value in before_flags.items()), 'Collection flags changed; inspect deployment configuration'
print('Runtime collection flags:',{k:os.environ.get(k) for k in ('COLLECT_ENABLED','NEWS_THUMBNAILS_ENABLED','GOVERNMENT_FULLTEXT_AUTO')})
print('RUNTIME_VERIFIED revision='+manifest['revision'])
