"""Consistent SQLite + referenced private pictures snapshot. Pause writers first.

Uses stdlib only, so backup also runs via stdin in the previous image.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


def digest(file):
    value = hashlib.sha256()
    with file.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def checked_file(base, key):
    if not re.fullmatch(r'[1-9][0-9]*/[0-9a-f]{32}/[0-9a-f]{64}\.(jpg|png|webp)', key):
        raise ValueError('Invalid image reference')
    file = (base/key).resolve()
    if not file.is_relative_to(base.resolve()):
        raise ValueError('Image outside backup root')
    return file


def backup(db, destination):
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Backup destination must be empty')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    saved = destination/'news.sqlite3'
    with closing(sqlite3.connect(db)) as origin, closing(sqlite3.connect(saved)) as target:
        origin.backup(target)
    images = []
    with closing(sqlite3.connect(saved)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='article_assets'").fetchone()
        rows = conn.execute('SELECT object_key FROM article_assets').fetchall() if exists else []
    for (key,) in rows:
        source = checked_file(db.parent/'news-images', key)
        target = checked_file(destination/'news-images', key)
        if not source.is_file():
            raise ValueError('Referenced image file missing; backup incomplete')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source, target)
        images.append({'key': key, 'sha256': digest(target), 'bytes': target.stat().st_size})
    manifest = {'database_sha256': digest(saved), 'images': images}
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def restore(source, destination):
    manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if digest(source/'news.sqlite3') != manifest['database_sha256']:
        raise ValueError('Database backup checksum mismatch')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Restore only into an empty destination')
    for image in manifest['images']:
        file = checked_file(source/'news-images', image['key'])
        if digest(file) != image['sha256'] or file.stat().st_size != image['bytes']:
            raise ValueError('Image backup checksum mismatch')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copyfile(source/'news.sqlite3', destination/'news.sqlite3')
    for image in manifest['images']:
        target = checked_file(destination/'news-images', image['key'])
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(checked_file(source/'news-images', image['key']), target)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('backup', 'restore'))
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.mode == 'backup':
        result = backup(Path(os.environ.get('NEWS_DB_PATH', '/data/news.sqlite3')), args.destination)
    else:
        if args.source is None:
            parser.error('--source required')
        result = restore(args.source, args.destination)
    print(json.dumps({'images': len(result['images']), 'destination': str(args.destination)}))
