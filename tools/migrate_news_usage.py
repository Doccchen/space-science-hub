"""Explicit copy-before-delete migration of legacy news rows into their own ledger."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import uuid

from backend import ai,news_limits


def migrate():
    source = ai.Settings.environment().db
    target = news_limits.usage_path()
    migrated_marker=target.with_suffix('.migrated')
    if not source.is_file(): raise RuntimeError('Existing legacy ledger required')
    if migrated_marker.exists() and not target.is_file():raise RuntimeError('Migrated news ledger missing; restore it before proceeding')
    if source.resolve() == target.resolve(): raise RuntimeError('News ledger must be independent')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = source.parent / ('news-usage-split-'+stamp+'-'+uuid.uuid4().hex[:8])
    for path in (source,target):
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone()
                if path==target and migrated_marker.exists() and not exists:raise RuntimeError('Migrated ledger schema missing')
                if exists and db.execute("SELECT 1 FROM requests WHERE status='pending'").fetchone():
                    raise RuntimeError('A ledger has pending requests; quiesce it before migration')
    backup.mkdir(mode=0o700)
    for path in (source,target):
        if path.is_file():
            with closing(sqlite3.connect(path)) as db,closing(sqlite3.connect(backup/path.name)) as saved:
                db.backup(saved)
    budget = news_limits.budget(news_limits.baseline(),initialize=True)
    if target.is_file():
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            budget.initialized=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='requests'").fetchone())
    budget.ensure_storage()
    with closing(sqlite3.connect(source)) as old,closing(sqlite3.connect(target)) as new:
        old.row_factory = sqlite3.Row
        rows = old.execute("SELECT * FROM requests WHERE substr(id,1,5)='news-'").fetchall()
        if any(row['status']=='pending' for row in rows):
            raise RuntimeError('Legacy news request is still pending; quiesce it before migration')
        columns = [row[1] for row in old.execute('PRAGMA table_info(requests)')]
        if columns != [row[1] for row in new.execute('PRAGMA table_info(requests)')]: raise RuntimeError('Ledger schema differs')
        for row in rows:
            existing = new.execute('SELECT * FROM requests WHERE id=?',(row['id'],)).fetchone()
            values = list(row)
            if existing and tuple(existing) != tuple(values): raise RuntimeError('Conflicting news ledger record')
            if not existing:
                new.execute('INSERT INTO requests VALUES('+','.join('?' for _ in values)+')',values)
        new.commit()  # Durable verified copy first; interruption before cleanup is safely retryable.
        for row in rows:
            old.execute('DELETE FROM requests WHERE id=?',(row['id'],))
        old.commit()
    migrated_marker.write_text('News ledger is independent; missing files require restoration\n')
    return {'migrated_news_requests':len(rows),'backup':str(backup),'model_calls':0}


def main():
    news_limits.initialize()
    print(json.dumps(migrate()))


if __name__ == '__main__': main()
