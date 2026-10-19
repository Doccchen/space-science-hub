import json
import sqlite3
import time
import uuid
from contextlib import contextmanager


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'files').mkdir(exist_ok=True)
        (self.root / 'jobs').mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, hash TEXT NOT NULL,
                    filename TEXT NOT NULL, size INTEGER NOT NULL, title TEXT NOT NULL,
                    authors TEXT DEFAULT '', year TEXT DEFAULT '', doi TEXT DEFAULT '',
                    version INTEGER DEFAULT 1, status TEXT DEFAULT 'queued',
                    error TEXT DEFAULT '', coverage TEXT DEFAULT '{}', metadata_edited INTEGER DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(owner, hash));
                CREATE TABLE IF NOT EXISTS blocks (
                    id TEXT PRIMARY KEY, paper TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, page INTEGER NOT NULL, section TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, text TEXT NOT NULL, bbox TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS block_scope ON blocks(paper, version, ordinal);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, paper TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    owner TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
                    attempt INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    error TEXT DEFAULT '', duration REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS answers (
                    id TEXT PRIMARY KEY, paper TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    owner TEXT NOT NULL, version INTEGER NOT NULL, request_key TEXT NOT NULL,
                    question TEXT NOT NULL, result TEXT, state TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(owner, request_key));
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, paper TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    owner TEXT NOT NULL, version INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT NOT NULL,
                    created REAL NOT NULL, state TEXT NOT NULL, model INTEGER NOT NULL,
                    duration REAL DEFAULT 0, tokens INTEGER DEFAULT 0, UNIQUE(owner,request_key));
                CREATE TABLE IF NOT EXISTS visitors (
                    owner TEXT PRIMARY KEY, expires REAL NOT NULL, ip_digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS upload_events (
                    id TEXT PRIMARY KEY, ip_digest TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS network_usage (
                    request_id TEXT PRIMARY KEY, ip_digest TEXT NOT NULL, created REAL NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'reader.sqlite3', timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        now = time.time()
        with self.connect() as db:
            db.execute("UPDATE papers SET status='interrupted',error='服务重启中断了解析，请手动重试。' WHERE status='parsing'")
            db.execute("UPDATE tasks SET state='interrupted',error='服务重启中断',updated=? WHERE state='running'", (now,))
            db.execute("UPDATE answers SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE usage SET state='interrupted' WHERE state='running'")
        # Jobs are disposable; queued jobs re-read the original PDF on startup.
        for file in (self.root / 'jobs').glob('*.json'):
            file.unlink(missing_ok=True)
        with self.connect() as db:
            live = {r['id'] for r in db.execute('SELECT id FROM papers')}
        for file in (self.root / 'files').glob('*.pdf'):
            if file.stem not in live:
                file.unlink(missing_ok=True)
        for file in (self.root / 'files').glob('*.upload'):
            file.unlink(missing_ok=True)

    @staticmethod
    def public(row):
        item = dict(row)
        item.pop('owner', None)
        item.pop('hash', None)
        item['coverage'] = json.loads(item['coverage'])
        return item

    def blocks(self, paper, version):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM blocks WHERE paper=? AND version=? ORDER BY ordinal', (paper, version))]
