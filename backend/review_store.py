"""Private admin persistence. Additive migration preserves news and review history."""
import json
import sqlite3
from contextlib import closing
from . import news, reading
from .locking import operation_lock
from .reading_policy import source_policy


def migrate(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_drafts'").fetchone() is None:
        if conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
            target = news.DB_PATH.with_name(news.DB_PATH.name+'.before-v5.sqlite3')
            if not target.exists():
                with closing(sqlite3.connect(news.DB_PATH)) as src, closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS admin_user (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL,
      password_hash TEXT NOT NULL, failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS review_drafts (article_id INTEGER PRIMARY KEY REFERENCES articles(id), revision INTEGER NOT NULL,
      document TEXT NOT NULL, candidates TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_jobs (id TEXT PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES articles(id),
      kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', result TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS article_assets (id TEXT PRIMARY KEY, article_id INTEGER NOT NULL REFERENCES articles(id),
      content_version TEXT NOT NULL, source_url TEXT NOT NULL, object_key TEXT NOT NULL,
      mime TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, caption TEXT NOT NULL,
      credit TEXT NOT NULL, permission TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS admin_audit (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, article_id INTEGER,
      action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


def audit(conn, actor, article_id, action, detail):
    conn.execute('INSERT INTO admin_audit(actor,article_id,action,detail,created_at) VALUES(?,?,?,?,?)',
                 (actor, article_id, action, detail, news.now()))


def article(conn, article_id):
    row = conn.execute('SELECT a.*,s.name AS source_name FROM articles a JOIN sources s ON s.id=a.source_id WHERE a.id=?', (article_id,)).fetchone()
    if row is None:
        raise ValueError('Article not found')
    return dict(row)


def save_draft(article_id, document, revision, actor, candidates=None, conn=None):
    if conn is None:
        with operation_lock(news.DB_PATH, timeout=10), news.connect() as db:
            return save_draft(article_id, document, revision, actor, candidates, db)
    item = article(conn, article_id)
    if source_policy(item['source_id']) != 'government_candidate':
        raise ValueError('This source is link-only')
    document = dict(document)
    document.update(original_url=item['original_url'], mode='full', reviewer=actor, reviewed_at=news.now())
    serialized = reading.validate(document)
    current = conn.execute('SELECT revision,candidates FROM review_drafts WHERE article_id=?', (article_id,)).fetchone()
    actual = current['revision'] if current else 0
    if revision != actual:
        raise ValueError('Draft changed; reload before saving')
    images = json.dumps(candidates, ensure_ascii=False) if candidates is not None else current['candidates'] if current else '[]'
    conn.execute('''INSERT INTO review_drafts VALUES(?,?,?,?,?) ON CONFLICT(article_id) DO UPDATE SET
      revision=excluded.revision,document=excluded.document,candidates=excluded.candidates,updated_at=excluded.updated_at''',
                 (article_id, actual+1, serialized, images, news.now()))
    audit(conn, actor, article_id, 'save_draft', str(actual+1))
    return actual+1
