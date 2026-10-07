"""Explicitly migrated, shared resource directory; no startup imports or cache."""
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from . import news

SCHEMA = 1


class ManagementError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def path():
    return Path(os.environ.get('MANAGEMENT_DB_PATH', str(news.DB_PATH.parent / 'site-management.sqlite3')))


def marker():
    # Retained independently so a missing active database never revives old JSON.
    return path().with_suffix('.resources-enabled')


@contextmanager
def connection(write=False):
    target = path()
    if not target.is_file():
        raise ManagementError('资料管理库尚未迁移或不可用。', 503)
    db = None
    try:
        db = sqlite3.connect(target.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'),
                             uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if write:
            db.execute('BEGIN IMMEDIATE')
        metadata = db.execute('SELECT version FROM schema_meta WHERE id=1').fetchone()
        if metadata is None or metadata[0] != SCHEMA:
            raise ManagementError('资料管理库版本不兼容。', 503)
        yield db
        if write:
            db.commit()
    except sqlite3.IntegrityError:
        raise ManagementError('资料 ID 或文件路径已存在，请重新核对。') from None
    except sqlite3.Error:
        raise ManagementError('资料管理库暂不可用，请检查数据库或写入锁。', 503) from None
    finally:
        if db:
            db.close()


def active():
    if marker().exists():
        return True
    if not path().exists():
        return False
    with connection() as db:
        return bool(db.execute('SELECT resources_active FROM schema_meta WHERE id=1').fetchone()[0])


def require_active():
    if not active():
        raise ManagementError('请先在服务器显式迁移资料目录。', 503)


def initialize():
    target = path()
    if marker().exists() and not target.is_file():
        raise ManagementError('已启用的资料库丢失，请恢复备份，不能重新导入旧目录。', 503)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Existing or damaged databases must never be silently repaired/reimported.
        with connection():
            pass
        return
    with closing(sqlite3.connect(target, timeout=2)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS schema_meta(id INTEGER PRIMARY KEY CHECK(id=1),
            version INTEGER NOT NULL, resources_active INTEGER NOT NULL DEFAULT 0);
          INSERT OR IGNORE INTO schema_meta VALUES(1,1,0);
          CREATE TABLE IF NOT EXISTS resource_items(id TEXT PRIMARY KEY, object_key TEXT NOT NULL UNIQUE,
            record TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS resource_revisions(resource_id TEXT NOT NULL, revision INTEGER NOT NULL,
            record TEXT NOT NULL, actor TEXT NOT NULL, operation TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(resource_id,revision), FOREIGN KEY(resource_id) REFERENCES resource_items(id));
          CREATE TABLE IF NOT EXISTS management_audit(id INTEGER PRIMARY KEY, resource_id TEXT,
            revision INTEGER, actor TEXT NOT NULL, operation TEXT NOT NULL, created_at TEXT NOT NULL,
            summary TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS resource_checks(id INTEGER PRIMARY KEY, resource_id TEXT NOT NULL,
            checked_at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS resource_checks_time ON resource_checks(checked_at);
        ''')
        db.commit()


def record(row):
    return {**json.loads(row['record']), 'revision': row['revision']}


def get(db, identity):
    row = db.execute('SELECT * FROM resource_items WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise ManagementError('资料不存在。', 404)
    return row


def write_record(db, item, revision, actor, operation, changed):
    text = json.dumps(item.model_dump(), ensure_ascii=False)
    db.execute('''INSERT INTO resource_items VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      object_key=excluded.object_key,record=excluded.record,revision=excluded.revision,
      updated_at=excluded.updated_at''', (item.id, item.object_key, text, revision, item.updated_at))
    db.execute('INSERT INTO resource_revisions VALUES(?,?,?,?,?,?)',
               (item.id, revision, text, actor, operation, item.updated_at))
    db.execute('INSERT INTO management_audit(resource_id,revision,actor,operation,created_at,summary) VALUES(?,?,?,?,?,?)',
               (item.id, revision, actor, operation, item.updated_at, json.dumps(changed, ensure_ascii=False)))


def migrate(source, actor='server-migration'):
    from .resources import Resource, object_url
    try:
        values = json.loads(Path(source).read_text(encoding='utf-8'))
        if not isinstance(values, list):
            raise ValueError()
        items = [Resource.model_validate(value) for value in values]
        if len({item.id for item in items}) != len(items) or len({item.object_key for item in items}) != len(items):
            raise ValueError()
        for item in items:
            object_url(item.object_key)
            if item.cover_key:
                object_url(item.cover_key, cover=True)
    except (ValueError, TypeError, OSError):
        raise ManagementError('源目录校验失败；未导入资料。', 400) from None
    initialize()
    with connection(write=True) as db:
        enabled = db.execute('SELECT resources_active FROM schema_meta WHERE id=1').fetchone()[0]
        if not enabled:
            if db.execute('SELECT COUNT(*) FROM resource_items').fetchone()[0]:
                raise ManagementError('未启用的资料库包含记录，请先人工检查。')
            for item in items:
                write_record(db, item, 1, actor, 'import', ['initial_import'])
            db.execute('UPDATE schema_meta SET resources_active=1 WHERE id=1')
        rows = db.execute('SELECT id,object_key FROM resource_items ORDER BY id').fetchall()
    marker().write_text('resources database is authoritative\n', encoding='utf-8')
    original = {item.id: item.object_key for item in items}
    current = {row['id']: row['object_key'] for row in rows}
    return {'imported': not bool(enabled), 'source_count': len(items), 'current_count': len(rows),
            'source_matches_current_ids_and_paths': original == current,
            'changed_ids': sorted(key for key in original.keys() | current.keys() if original.get(key) != current.get(key))}


def public_items():
    from .resources import Resource, object_url
    try:
        with connection() as db:
            items = [Resource.model_validate(json.loads(row['record'])) for row in db.execute('SELECT record FROM resource_items')]
        for item in items:
            object_url(item.object_key)
        return sorted((item for item in items if item.published), key=lambda item: (item.display_order, item.id))
    except (ValueError, TypeError):
        raise ManagementError('资料目录内容无效。', 503) from None


def reserve_check(identity):
    now = time.time()
    with connection(write=True) as db:
        get(db, identity)
        db.execute('DELETE FROM resource_checks WHERE checked_at<?', (now - 3600,))
        if (db.execute('SELECT 1 FROM resource_checks WHERE resource_id=? AND checked_at>?', (identity, now - 10)).fetchone()
                or db.execute('SELECT COUNT(*) FROM resource_checks WHERE checked_at>?', (now - 60,)).fetchone()[0] >= 10):
            raise ManagementError('文件检查过于频繁，请稍后重试。', 429)
        db.execute('INSERT INTO resource_checks(resource_id,checked_at) VALUES(?,?)', (identity, now))
