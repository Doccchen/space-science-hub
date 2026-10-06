"""Local-only reviewed edition import / withdrawal. Never downloads arbitrary URLs."""
import argparse
import json
from pathlib import Path
from backend import news, reading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    publish = commands.add_parser('import')
    publish.add_argument('file', type=Path)
    publish.add_argument('--republish', action='store_true', help='Explicitly approve publication after withdrawal')
    batch = commands.add_parser('import-missing')
    batch.add_argument('directory', type=Path)
    revoke = commands.add_parser('withdraw')
    revoke.add_argument('article_id', type=int)
    revoke.add_argument('--reviewer', required=True)
    revoke.add_argument('--reason', required=True)
    args = parser.parse_args()
    news.initialize()
    if args.command == 'import-missing':
        result = []
        for file in sorted(args.directory.glob('*.json')):
            if file.stat().st_size > reading.MAX_DOCUMENT_BYTES:
                parser.error('File exceeds edition byte budget')
            document = json.loads(file.read_text(encoding='utf-8'))
            reading.validate(document)
            if document['mode'] != 'full':
                result.append({'file': file.name, 'status': 'legacy_guide_not_published'})
                continue
            with news.connect() as conn:
                existing = conn.execute('''SELECT a.id,h.version FROM articles a LEFT JOIN reading_heads h ON h.article_id=a.id
                  WHERE a.canonical_url=?''', (news.canonical_url(document['original_url']),)).fetchone()
            if not existing:
                result.append({'file': file.name, 'status': 'article_missing'})
            else:
                result.append(reading.publish(document, only_if_missing=True))
    elif args.command == 'import':
        if args.file.stat().st_size > reading.MAX_DOCUMENT_BYTES:
            parser.error('File exceeds edition byte budget')
        result = reading.publish(json.loads(args.file.read_text(encoding='utf-8')), republish=args.republish)
    else:
        reading.withdraw(args.article_id, args.reviewer, args.reason)
        result = {'article_id': args.article_id, 'withdrawn': True}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
