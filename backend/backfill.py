"""Bounded, resumable publisher archive traversal; never runs at web startup."""
import argparse
import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from . import news
from .html_sources import BudgetExceeded, PublisherHTTP, listing_page, parse_detail, parse_listing
from .locking import operation_lock


def boundary(value):
    # A CLI day means a Beijing calendar day, including 2025-10-01.
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone(timedelta(hours=8)))
    return date.astimezone(timezone.utc).isoformat(timespec='seconds')


def run_state(run_id):
    with news.connect() as conn:
        row = conn.execute('SELECT * FROM backfill_runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown backfill run')
    return dict(row)


def report(run_id):
    run = run_state(run_id)
    with news.connect() as conn:
        counts = {row[0]: row[1] for row in conn.execute(
            'SELECT status,COUNT(*) FROM backfill_items WHERE run_id=? GROUP BY status', (run_id,))}
        dates = conn.execute("SELECT MIN(published_at),MAX(published_at) FROM backfill_items WHERE run_id=? AND status='stored'", (run_id,)).fetchone()
    run.update(counts=counts, actual_earliest=dates[0], actual_latest=dates[1], stats=json.loads(run['stats']))
    return run


async def execute(source_id, *, start='2025-10-01', end=None, resume=None,
                  max_pages=5, max_articles=50, max_seconds=240, dry_run=False, client=None, retry_undated=False):
    if source_id not in news.SOURCES or news.SOURCES[source_id]['collector_kind'] != 'html':
        raise ValueError('Historical backfill is limited to the four reviewed domestic publishers')
    if max_pages < 2 or max_articles < 1 or max_seconds < 1:
        raise ValueError('Require max-pages>=2, max-articles>=1, max-seconds>=1')
    if retry_undated and not resume:
        raise ValueError('Retry undated requires an existing run ID')
    with operation_lock(news.DB_PATH):
        news._initialize()
        start_at, end_at = boundary(start), boundary(end) if end else news.now()
        if start_at > end_at:
            raise ValueError('Start is after end')
        if resume:
            run = run_state(resume)
            if run['source_id'] != source_id:
                raise ValueError('Resume source mismatch')
            start_at, end_at = run['start_at'], run['end_at']
            if retry_undated and not dry_run:
                with news.connect() as conn:
                    conn.execute("UPDATE backfill_items SET status='pending',error=NULL WHERE run_id=? AND status='undated'", (run['id'],))
        else:
            run = dict(id=f'{source_id}-{uuid.uuid4().hex[:12]}', source_id=source_id,
                       start_at=start_at, end_at=end_at, next_page=0, total_pages=None, stats='{}')
            if not dry_run:
                with news.connect() as conn:
                    conn.execute('''INSERT INTO backfill_runs(id,source_id,start_at,end_at,created_at,updated_at,status)
                                    VALUES(?,?,?,?,?,?,'running')''',
                                 (run['id'], source_id, start_at, end_at, news.now(), news.now()))
        owned = client is None
        if owned:
            client = httpx.AsyncClient(timeout=15, trust_env=False)
        fetcher = PublisherHTTP(client, source_id)
        stats = json.loads(run['stats'])
        batch = {'pages': 0, 'details': 0, 'inserted': 0, 'updated': 0, 'duplicates': 0,
                 'requests': 0, 'seconds': 0, 'errors': []}
        started = time.monotonic()
        deadline = started + max_seconds
        fetcher.deadline = deadline
        status = 'paused_budget'

        def budget():
            return batch['details'] >= max_articles or time.monotonic() >= deadline

        async def process(item):
            nonlocal status
            batch['details'] += 1
            try:
                record = parse_detail(source_id, await fetcher.get(item['url']), item)
                date = record['published_at']
                item_status = 'undated' if not date else 'outside' if not start_at <= date <= end_at else 'stored'
                if item_status == 'stored' and not dry_run:
                    with news.connect() as conn:
                        prior = conn.execute('SELECT content_hash FROM articles WHERE source_id=? AND canonical_url=?',
                                             (source_id, record['canonical_url'])).fetchone()
                    news.store_records([record])
                    count_key = 'inserted' if prior is None else 'duplicates' if prior['content_hash'] == record['content_hash'] else 'updated'
                    batch[count_key] += 1
                if not dry_run:
                    with news.connect() as conn:
                        conn.execute('UPDATE backfill_items SET status=?,error=NULL,published_at=?,attempts=attempts+1,last_attempt_at=? WHERE run_id=? AND url=?',
                                     (item_status, date, news.now(), run['id'], item['url']))
            except BudgetExceeded:
                raise
            except Exception as error:
                batch['errors'].append({'url': item['url'], 'error': str(error)[:300]})
                if not dry_run:
                    with news.connect() as conn:
                        conn.execute("UPDATE backfill_items SET status='failed',error=?,attempts=attempts+1,last_attempt_at=? WHERE run_id=? AND url=?",
                                     (str(error)[:300], news.now(), run['id'], item['url']))
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                    status = 'paused_throttle'
                    raise

        try:
            state = news.source_state(source_id)
            if state['retry_after_at'] and state['retry_after_at'] > news.now():
                raise ValueError('Publisher Retry-After is still active')
            await fetcher.check_robots()
            # Always inspect the newest page to detect changed archive numbering.
            first_url = listing_page(source_id, 0)
            first_raw = await fetcher.get(first_url)
            batch['pages'] = 1
            first_items, total = parse_listing(source_id, first_raw, first_url)
            if total is None or total < 1:
                raise ValueError('Archive page count is not validated')
            changed = run['total_pages'] is not None and run['total_pages'] != total
            offset = 0 if changed else max(0, run['next_page'] - 1)
            if not dry_run:
                with news.connect() as conn:
                    conn.execute("UPDATE backfill_runs SET total_pages=?,status='running' WHERE id=?", (total, run['id']))
                    pending = [json.loads(row[0]) for row in conn.execute(
                        "SELECT listing FROM backfill_items WHERE run_id=? AND status='pending' ORDER BY url", (run['id'],))]
                for item in pending:
                    if budget():
                        break
                    await process(item)
            while offset < total and not budget():
                url = listing_page(source_id, offset, total)
                if offset == 0:
                    items = first_items
                else:
                    if batch['pages'] >= max_pages:
                        break
                    raw = await fetcher.get(url)
                    batch['pages'] += 1
                    items, observed_total = parse_listing(source_id, raw, url, known_total=total)
                    if observed_total is not None and observed_total != total:
                        raise ValueError('Archive page count changed during traversal; resume to re-scan')
                if not items:
                    raise ValueError('Unexpected empty archive page')
                if not dry_run:
                    with news.connect() as conn:
                        for item in items:
                            conn.execute('INSERT OR IGNORE INTO backfill_items(run_id,url,listing) VALUES(?,?,?)',
                                         (run['id'], item['url'], json.dumps(item, ensure_ascii=False)))
                        # All URLs are queued before advancing; budget-limited details aren't lost.
                        conn.execute('UPDATE backfill_runs SET next_page=? WHERE id=?', (offset + 1, run['id']))
                for item in items:
                    if budget():
                        break
                    if not dry_run:
                        with news.connect() as conn:
                            item_state = conn.execute('SELECT status FROM backfill_items WHERE run_id=? AND url=?',
                                                      (run['id'], item['url'])).fetchone()[0]
                        if item_state != 'pending':
                            continue
                    await process(item)
                offset += 1
            # Failed URLs never precede fresh pending work or consume the whole
            # discovery budget. Rotate retries by attempts/time to avoid starvation.
            if not dry_run and not budget():
                with news.connect() as conn:
                    retries = [json.loads(row[0]) for row in conn.execute(
                        "SELECT listing FROM backfill_items WHERE run_id=? AND status='failed' "
                        "ORDER BY attempts,COALESCE(last_attempt_at,''),url LIMIT ?",
                        (run['id'], max(1, max_articles // 4)))]
                for item in retries:
                    if budget():
                        break
                    await process(item)
            if not dry_run:
                state = run_state(run['id'])
                with news.connect() as conn:
                    incomplete = conn.execute("SELECT COUNT(*) FROM backfill_items WHERE run_id=? AND status IN ('pending','failed','undated')", (run['id'],)).fetchone()[0]
                if state['next_page'] >= total:
                    status = 'enumerated_with_gaps' if incomplete else 'enumerated_complete'
            else:
                status = 'dry_run'
        except BudgetExceeded:
            status = 'paused_budget'
        except Exception as error:
            if status != 'paused_throttle':
                status = 'paused_error'
            batch['errors'].append({'error': f'{type(error).__name__}: {error}'[:300]})
        finally:
            batch['requests'] = fetcher.request_count
            batch['seconds'] = round(time.monotonic() - started, 2)
            try:
                import resource
                batch['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                stats['peak_rss_kib'] = max(stats.get('peak_rss_kib', 0), batch['peak_rss_kib'])
            except ImportError:
                pass
            if owned:
                await client.aclose()
            for name in ('pages', 'details', 'inserted', 'updated', 'duplicates', 'requests', 'seconds'):
                stats[name] = stats.get(name, 0) + batch[name]
            if not dry_run:
                with news.connect() as conn:
                    conn.execute('UPDATE backfill_runs SET updated_at=?,status=?,stats=? WHERE id=?',
                                 (news.now(), status, json.dumps(stats), run['id']))
        result = report(run['id']) if not dry_run else {'status': status, 'start_at': start_at, 'end_at': end_at}
        result['batch'] = batch
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=[key for key, value in news.SOURCES.items() if value['collector_kind'] == 'html'])
    parser.add_argument('--since', default='2025-10-01')
    parser.add_argument('--until', help='Fixed end datetime; default is this new run start time')
    parser.add_argument('--resume', help='Run ID; uses its saved date range')
    parser.add_argument('--max-pages', type=int, default=5)
    parser.add_argument('--max-articles', type=int, default=50)
    parser.add_argument('--max-seconds', type=int, default=240)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--retry-undated', action='store_true', help='Reparse undated URLs from this resumed run after a parser fix')
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args.source, start=args.since, end=args.until, resume=args.resume,
                                    max_pages=args.max_pages, max_articles=args.max_articles,
                                    max_seconds=args.max_seconds, dry_run=args.dry_run, retry_undated=args.retry_undated))
    except RuntimeError as error:
        if 'operation lock' not in str(error):
            raise
        print(json.dumps({'id': args.resume, 'status': 'paused_lock', 'error': str(error)}))
        raise SystemExit(3)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] in {'paused_error', 'paused_throttle'}:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
