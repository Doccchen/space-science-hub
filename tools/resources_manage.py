"""Server-only explicit directory migration, consistent backup and legacy export."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import management_store as store, resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('migrate', 'inspect', 'backup', 'export'))
    parser.add_argument('--source', type=Path, default=resources.ROOT / 'content/resources.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'migrate':
            result = store.migrate(args.source)
        elif args.mode == 'inspect':
            result = {'active': store.active(), 'database': str(store.path()), 'marker': str(store.marker())}
            if result['active']:
                with store.connection() as db:
                    result['items'] = db.execute('SELECT COUNT(*) FROM resource_items').fetchone()[0]
        else:
            store.require_active()
            if args.output is None or args.output.exists():
                parser.error('--output must name a new destination')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if args.mode == 'backup':
                # Exclusive creation avoids accidentally replacing a backup.
                with args.output.open('xb'):
                    pass
                with store.connection() as origin, closing(sqlite3.connect(args.output)) as target:
                    origin.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise store.ManagementError('备份完整性检查失败。')
                result = {'backup': str(args.output), 'marker_required_on_restore': True}
            else:
                with store.connection() as db:
                    items = [json.loads(row['record']) for row in db.execute('SELECT record FROM resource_items')]
                items.sort(key=lambda item: (item['display_order'], item['id']))
                with args.output.open('x', encoding='utf-8') as handle:
                    handle.write(json.dumps(items, ensure_ascii=False, indent=2) + '\n')
                result = {'exported': len(items), 'output': str(args.output)}
        print(json.dumps(result, ensure_ascii=False))
    except (store.ManagementError, OSError, sqlite3.Error) as error:
        message = error.message if isinstance(error, store.ManagementError) else '资料管理操作失败，请检查路径、权限及数据库。'
        parser.exit(1, message + '\n')


if __name__ == '__main__':
    main()
