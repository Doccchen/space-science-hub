"""Isolated review UI preview. Public history is copied; source network jobs disabled."""
import asyncio
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
target = ROOT/'data/admin-preview/news.sqlite3'
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    with closing(sqlite3.connect(f'file:{(ROOT/"data/news.sqlite3").as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
os.environ.update(NEWS_DB_PATH=str(target), ADMIN_ORIGIN='http://127.0.0.1:18080', REVIEW_WORKER_ENABLED='0', COLLECT_ENABLED='0')

if __name__ == '__main__':
    from backend import news, admin_auth, review_store
    from backend.admin_app import app
    import uvicorn
    news.initialize()
    admin_auth.initialize_user('preview', 'preview-review-only-2026')
    for path in (ROOT/'content/reading').glob('*.json'):
        document = json.loads(path.read_text(encoding='utf-8'))
        if document['mode'] != 'full':
            continue
        with news.connect() as conn:
            article = conn.execute('SELECT id FROM articles WHERE canonical_url=?', (news.canonical_url(document['original_url']),)).fetchone()
            draft = article and conn.execute('SELECT revision FROM review_drafts WHERE article_id=?', (article['id'],)).fetchone()
        if article and not draft:
            review_store.save_draft(article['id'], document, 0, 'preview')
    @app.middleware('http')
    async def slow_save(request, call_next):
        if request.method == 'POST' and request.url.path.endswith('/draft'):
            await asyncio.sleep(2)
        return await call_next(request)
    uvicorn.run(app, host='127.0.0.1', port=18080)
