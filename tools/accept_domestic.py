"""Server assertions for enabled domestic sources and upgrade preservation."""
import asyncio
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import httpx

from backend import news
from backend.html_sources import PublisherHTTP, listing_page, parse_detail, parse_listing
from backend.locking import operation_lock
from tools.accept_news import api, identities

ROOT = news.DB_PATH.parent / 'domestic-acceptance'


def pages(source=None, category=None):
    from urllib.parse import urlencode
    ids, cursor = [], None
    for _ in range(10000):
        params = {'limit': 2}
        if source:
            params['source'] = source
        if category:
            params['category'] = category
        if cursor:
            params['cursor'] = cursor
        result = api('/api/news?' + urlencode(params))
        ids.extend(row['id'] for row in result['items'])
        cursor = result['next_cursor']
        if not cursor:
            break
    else:
        raise AssertionError('Pagination never terminated')
    expected, cursor = [], None
    while True:
        result = news.list_articles(source=source, category=category, cursor=cursor, limit=50)
        expected.extend(row['id'] for row in result['items'])
        cursor = result['next_cursor']
        if not cursor:
            break
    assert ids == expected and len(ids) == len(set(ids)), 'Pagination lost/repeated records'
    return len(ids)


async def validate():
    result = {'started_at': news.now(), 'sources': {}, 'categories': {}, 'blocked_sources': []}
    enabled = [row for row in news.sources_status() if row['collector_kind'] == 'html' and row['enabled']]
    assert enabled, 'No domestic source was enabled; cannot claim domestic acceptance'
    with operation_lock(news.DB_PATH):
        for row in news.sources_status():
            if row['collector_kind'] == 'html' and not row['enabled']:
                result['blocked_sources'].append(row['id'])
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            for state in enabled:
                source = state['id']
                assert state['stored_articles'] >= 3 and not state['last_error'], state
                fetcher = PublisherHTTP(client, source)
                await fetcher.check_robots()
                url = listing_page(source, 0)
                items, total = parse_listing(source, await fetcher.get(url), url)
                samples = []
                for item in items[:3]:
                    samples.append(parse_detail(source, await fetcher.get(item['url']), item))
                news.store_records(samples)
                before = identities()
                news.store_records(samples)
                assert identities() == before, 'Repeated real detail payload changed identities'
                previous = news.source_state(source)
                def failure(request):
                    raise httpx.ConnectError('Acceptance: simulated upstream failure', request=request)
                try:
                    async with httpx.AsyncClient(transport=httpx.MockTransport(failure)) as failing:
                        collection = await news.collect_source(failing, source)
                    assert 'error' in collection
                    assert identities() == before
                    failed_state = next(item for item in api('/api/news/sources')['items'] if item['id'] == source)
                    assert failed_state['last_error'] is True
                    assert failed_state['last_success_at'] == previous['last_success_at']
                    count = pages(source=source)
                    assert count >= 3
                finally:
                    with news.connect() as conn:
                        conn.execute('UPDATE sources SET last_attempt_at=?,last_success_at=?,last_error=?,last_result=?,retry_after_at=? WHERE id=?',
                                     (previous['last_attempt_at'], previous['last_success_at'], previous['last_error'],
                                      previous['last_result'], previous['retry_after_at'], source))
                result['sources'][source] = {'stored': count, 'sample_titles': [item['title'] for item in samples],
                                            'repeat_payload': 'passed', 'failure_history': 'passed',
                                            'archive_pages_advertised': total, 'requests': fetcher.request_count,
                                            'historical_coverage': 'not yet verified; use separate backfill reports'}
        for category in news.CATEGORIES:
            result['categories'][category] = pages(category=category)
        assert pages('nasa') and pages('esa'), 'Original RSS history missing'
        backup_path = ROOT / 'backup.sqlite3'
        with closing(sqlite3.connect(news.DB_PATH)) as origin, closing(sqlite3.connect(backup_path)) as backup:
            origin.backup(backup)
        # Restore to an independent database, never overwrite the live DB for testing.
        restore_path = ROOT / 'restore-check.sqlite3'
        with closing(sqlite3.connect(backup_path)) as origin, closing(sqlite3.connect(restore_path)) as restored:
            origin.backup(restored)
            assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            restored.row_factory = sqlite3.Row
            rows = [dict(row) for row in restored.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id')]
            assert rows == identities()
        result['isolated_backup_restore'] = 'passed'
        result['baseline'] = identities()
    result['completed_at'] = news.now()
    result['browser_interaction'] = 'pending'
    return result


def main():
    ROOT.mkdir(exist_ok=True)
    phase = sys.argv[1]
    if phase == 'before':
        result = asyncio.run(validate())
        upgrade_baseline = news.DB_PATH.parent / 'upgrade-baseline.json'
        if upgrade_baseline.exists():
            previous = json.loads(upgrade_baseline.read_text())
            current = {row['id']: row for row in identities()}
            assert all(current.get(row['id']) == row for row in previous), 'Upgrade changed old identities'
            result['v1_identity_preservation'] = 'passed'
        (ROOT / 'before.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    elif phase == 'after':
        result = json.loads((ROOT / 'before.json').read_text(encoding='utf-8'))
        current = {row['id']: row for row in identities()}
        assert all(current.get(row['id']) == row for row in result['baseline']), 'Rebuild lost article identities'
        result['container_recreation'] = 'passed'
        result['post_recreation_articles'] = pages()
        (ROOT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        raise ValueError('Use before or after')
    try:
        import resource
        result['acceptance_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:
        pass
    (ROOT / ('before.json' if phase == 'before' else 'result.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
