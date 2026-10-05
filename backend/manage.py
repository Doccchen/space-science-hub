"""Container-only administration; no public collection or source management API."""
import argparse
import asyncio
import json

import httpx

from . import news
from .html_sources import PublisherHTTP, listing_page, parse_detail, parse_listing
from .locking import operation_lock


async def probe(source_id, enable=False):
    if news.SOURCES[source_id]['collector_kind'] != 'html':
        raise ValueError('This command probes fixed HTML news sources')
    with operation_lock(news.DB_PATH):
        news._initialize()
        state = news.source_state(source_id)
        if state['retry_after_at'] and state['retry_after_at'] > news.now():
            raise ValueError(f'Publisher Retry-After active until {state["retry_after_at"]}')
        records = []
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            fetcher = PublisherHTTP(client, source_id)
            await fetcher.check_robots()
            url = listing_page(source_id, 0)
            items, total = parse_listing(source_id, await fetcher.get(url), url)
            if len(items) < 3:
                raise ValueError('Require at least three valid news samples before enabling')
            for item in items[:3]:
                raw = await fetcher.get(item['url'])
                records.append(parse_detail(source_id, raw, {**item, 'resolved_url': fetcher.last_url}))
        if enable:
            news.store_records(records)
            news.update_source(source_id, attempt=True)
            news.update_source(source_id, success=True, count=len(records))
            with news.connect() as conn:
                conn.execute('UPDATE sources SET enabled=1 WHERE id=?', (source_id,))
        result = {'source': source_id, 'enabled': enable, 'total_pages': total,
                  'requests': fetcher.request_count, 'robots_state': fetcher.robots_state, 'samples': records}
        folder = news.DB_PATH.parent / 'source-validation'
        folder.mkdir(exist_ok=True)
        (folder / f'{source_id}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('probe')
    p.add_argument('source', choices=[key for key, value in news.SOURCES.items() if value['collector_kind'] == 'html'])
    p.add_argument('--enable', action='store_true')
    p = sub.add_parser('disable')
    p.add_argument('source', choices=news.SOURCES)
    sub.add_parser('status')
    sub.add_parser('collect')
    args = parser.parse_args()
    if args.command == 'probe':
        result = asyncio.run(probe(args.source, args.enable))
    elif args.command == 'disable':
        with operation_lock(news.DB_PATH):
            news._initialize()
            with news.connect() as conn:
                conn.execute('UPDATE sources SET enabled=0 WHERE id=?', (args.source,))
        result = {'source': args.source, 'enabled': False, 'history_preserved': True}
    else:
        news.initialize()
        result = news.sources_status() if args.command == 'status' else asyncio.run(news.collect_all())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'collect' and any('error' in row or row.get('result') in {'partial', 'failed'} or
                                       row.get('skipped') == 'operation_locked' for row in result):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
