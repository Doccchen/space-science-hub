"""Isolated local preview: copy history, disable collection, import reviewed samples."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
target = ROOT/'data/reading-preview/news.sqlite3'
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    with closing(sqlite3.connect(f'file:{(ROOT/"data/news.sqlite3").as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
os.environ['NEWS_DB_PATH'] = str(target)
os.environ['COLLECT_ENABLED'] = '0'

if __name__ == '__main__':
    from backend import news, reading
    import json
    import uvicorn
    news.initialize()
    for path in (ROOT/'content/reading').glob('*.json'):
        document = json.loads(path.read_text(encoding='utf-8'))
        with news.connect() as conn:
            row = conn.execute('SELECT id FROM articles WHERE canonical_url=?', (news.canonical_url(document['original_url']),)).fetchone()
            exists = row and conn.execute('SELECT 1 FROM reading_heads WHERE article_id=?', (row['id'],)).fetchone()
        if row and not exists:
            reading.publish(document)
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8093)
