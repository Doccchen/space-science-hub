"""Versioned private context and job storage, independent of public editions."""
import sqlite3
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('Unsupported news-agent database version')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS news_contexts(article_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL, document TEXT NOT NULL, expires REAL NOT NULL,
                PRIMARY KEY(article_id,fingerprint));
              CREATE TABLE IF NOT EXISTS news_agent_conversations(id TEXT PRIMARY KEY,
                owner TEXT NOT NULL, article_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                config_version TEXT NOT NULL, content_version TEXT, session TEXT, expires REAL NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS news_agent_jobs(id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                conversation TEXT NOT NULL, request_id TEXT NOT NULL, question TEXT NOT NULL,
                kind TEXT NOT NULL, stage TEXT NOT NULL, created REAL NOT NULL,
                result TEXT, error TEXT, ledger_id TEXT, tool_calls INTEGER NOT NULL DEFAULT 0, tool_read_version TEXT,
                UNIQUE(owner,request_id));
              CREATE INDEX IF NOT EXISTS news_jobs_conversation ON news_agent_jobs(conversation,created);
              CREATE TABLE IF NOT EXISTS news_explanations(id TEXT PRIMARY KEY,
                owner TEXT NOT NULL, article_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                config_version TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE,
                result TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created REAL NOT NULL);
              PRAGMA user_version=1;
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def interrupt(self):
        with self.connection() as db:
            db.execute("UPDATE news_agent_jobs SET stage='interrupted',error='interrupted' "
                       "WHERE stage IN ('queued','reading','generating')")

    def cleanup(self, now):
        with self.connection() as db:
            db.execute('DELETE FROM news_contexts WHERE expires<?', (now,))
            db.execute('UPDATE news_agent_conversations SET deleted=1,session=NULL WHERE expires<?', (now,))
            db.execute('DELETE FROM news_explanations WHERE job_id IN (SELECT j.id FROM news_agent_jobs j '
                       'JOIN news_agent_conversations c ON c.id=j.conversation WHERE c.deleted=1)')
            db.execute("UPDATE news_agent_jobs SET question='',result=NULL WHERE conversation IN "
                       '(SELECT id FROM news_agent_conversations WHERE deleted=1)')
            db.execute('DELETE FROM news_agent_jobs WHERE created<?', (now - 30 * 86400,))
            db.execute('DELETE FROM news_agent_conversations WHERE expires<?', (now - 30 * 86400,))
