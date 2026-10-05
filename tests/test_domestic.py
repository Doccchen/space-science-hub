import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import backfill, news
from backend.app import app
from backend.html_sources import (SELECTORS, PublisherHTTP, collect_html, detail_allowed,
                                  listing_page, parse_date, parse_detail, parse_listing, request_allowed)
from backend.locking import operation_lock

FIXTURES = Path(__file__).parent / 'fixtures'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))


class DomesticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name) / 'news.sqlite3'
        news.initialize()

    def tearDown(self):
        news.DB_PATH = self.old_db
        self.temp.cleanup()

    def records(self, source):
        url = news.SOURCES[source]['url']
        items, _ = parse_listing(source, (FIXTURES / source / 'list.html').read_bytes(), url)
        result = []
        for number, sample in enumerate(MANIFEST[source]['details']):
            listing = next(item for item in items if item['url'] == sample['url'])
            result.append(parse_detail(source, (FIXTURES / source / f'detail-{number}.html').read_bytes(), listing))
        return result

    def test_real_server_structures_four_sources_and_twelve_details(self):
        for source in SELECTORS:
            for record in self.records(source):
                self.assertEqual(record['lang'], 'zh')
                self.assertEqual(record['published_precision'], 'day')
                self.assertEqual(record['published_origin'], 'detail')
                self.assertTrue(record['title'])
                self.assertLessEqual(len(record['summary']), 600)
                self.assertTrue(detail_allowed(source, record['original_url']))
            news.store_records(self.records(source))
            before = news.list_articles(source=source)['items']
            news.store_records(self.records(source))
            self.assertEqual([(r['id'], r['first_seen_at']) for r in before],
                             [(r['id'], r['first_seen_at']) for r in news.list_articles(source=source)['items']])

    def test_missing_publication_does_not_use_body_or_listing_event_date(self):
        source = 'cmse'
        listing = {'url': MANIFEST[source]['details'][0]['url'], 'list_date': '2025-10-01'}
        raw = (FIXTURES / source / 'detail-0.html').read_text(encoding='utf-8').replace('2026-08-28', '未提供')
        record = parse_detail(source, raw, listing)
        self.assertIsNone(record['published_at'])
        self.assertEqual(record['date_status'], 'missing')
        date, precision, status = parse_date('发布时间：2025-10-01')
        self.assertEqual(date, '2025-09-30T16:00:00+00:00')
        self.assertEqual(precision, 'day')
        self.assertEqual(backfill.boundary('2025-10-01'), date)
        self.assertLess(parse_date('2025-09-30')[0], date)
        self.assertEqual(parse_date('2025-02-30')[2], 'invalid')

    def test_structure_failure_plain_text_and_media_boundary(self):
        for source in SELECTORS:
            with self.assertRaises(ValueError):
                parse_listing(source, b'<html>site maintenance</html>', news.SOURCES[source]['url'])
            with self.assertRaises(ValueError):
                parse_detail(source, b'<h1>not the reviewed layout</h1>', {'url': MANIFEST[source]['details'][0]['url']})
        raw = (FIXTURES / 'cas_space' / 'list.html').read_text(encoding='utf-8')
        raw = raw.replace('</ul>', '<li><a href="https://evil.test/news">media</a></li></ul>')
        items, _ = parse_listing('cas_space', raw, news.SOURCES['cas_space']['url'])
        self.assertTrue(all('/article/' in item['url'] for item in items))
        detail = (FIXTURES / 'cmse' / 'detail-0.html').read_text(encoding='utf-8')
        detail = detail.replace('<p>', '<script>untrusted()</script><p>', 1)
        record = parse_detail('cmse', detail, {'url': MANIFEST['cmse']['details'][0]['url']})
        self.assertNotIn('untrusted', record['summary'])

    def test_actual_pagination_patterns_and_cas_public_api(self):
        self.assertTrue(listing_page('cnsa', 1, 301).endswith('index_10548744_300.html'))
        self.assertTrue(listing_page('cmse', 1).endswith('index_1.html'))
        self.assertIn('page=2', listing_page('landspace', 1))
        raw = (FIXTURES / 'cas_space' / 'page-1.json').read_bytes()
        items, total = parse_listing('cas_space', raw, listing_page('cas_space', 0))
        self.assertEqual(total, 8)
        self.assertEqual(len(items), 9)
        payload = json.loads(raw)
        payload['data']['rows'][0]['cid'] = 17
        filtered, _ = parse_listing('cas_space', json.dumps(payload), listing_page('cas_space', 0))
        self.assertEqual(len(filtered), 8)

    def test_cas_legacy_metadata_source_precedes_publication(self):
        for number, expected in [(129, '2025-12-09T16:00:00+00:00'), (54, '2022-07-26T16:00:00+00:00')]:
            raw = (FIXTURES / 'cas_space' / f'legacy-{number}.html').read_bytes()
            record = parse_detail('cas_space', raw, {'url': f'https://www.cas-space.com/article/{number}.html'})
            self.assertEqual(record['published_at'], expected)
            self.assertEqual(record['published_precision'], 'day')
            self.assertEqual(record['content_source'], '中科宇航')

    def test_url_and_redirect_scope_and_robots(self):
        self.assertFalse(request_allowed('cas_space', 'https://www.cas-space.com/list/ajax?page=1&pageSize=9&cid=17'))
        self.assertFalse(detail_allowed('landspace', 'https://www.landspace.com/news-detail.html?itemid=1&redirect=evil'))
        async def run():
            transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}))
            async with httpx.AsyncClient(transport=transport) as client:
                with self.assertRaises(ValueError):
                    await PublisherHTTP(client, 'cmse').get(news.SOURCES['cmse']['url'])
            transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b'User-agent: *\nDisallow: /'))
            async with httpx.AsyncClient(transport=transport) as client:
                fetcher = PublisherHTTP(client, 'cmse')
                await fetcher.check_robots()
                with self.assertRaises(ValueError):
                    await fetcher.get(news.SOURCES['cmse']['url'])
        with patch('backend.html_sources.DETAIL_DELAY', 0):
            asyncio.run(run())

    def test_category_cursor_binding_and_disabled_history(self):
        for source in SELECTORS:
            news.store_records(self.records(source))
        with patch.dict(os.environ, {'COLLECT_ENABLED': '0'}), TestClient(app) as client:
            page = client.get('/api/news?category=domestic_agency&limit=2').json()
            self.assertEqual(len(page['items']), 2)
            self.assertTrue(all(item['publisher_kind'] == 'agency' and item['region'] == 'domestic' for item in page['items']))
            cursor = page['next_cursor']
            self.assertEqual(client.get('/api/news', params={'category': 'commercial', 'cursor': cursor}).status_code, 400)
            self.assertEqual(client.get('/api/news?category=commercial&source=cnsa').status_code, 400)
            self.assertEqual(len(client.get('/api/news?source=cnsa').json()['items']), 3)
            source = next(row for row in client.get('/api/news/sources').json()['items'] if row['id'] == 'cnsa')
            self.assertEqual(source['enabled'], 0)
        seen, cursor = [], None
        while True:
            page = news.list_articles(category='commercial', cursor=cursor, limit=2)
            seen += [row['id'] for row in page['items']]
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(seen), 6)
        self.assertEqual(len(set(seen)), 6)

    def test_lock_blocks_other_operations(self):
        with operation_lock(news.DB_PATH), self.assertRaises(RuntimeError):
            with operation_lock(news.DB_PATH):
                pass

    def test_robots_redirect_to_publisher_home_is_inspected_without_opening_news_scope(self):
        async def run():
            visited = []
            def respond(request):
                visited.append(request.url.path)
                if request.url.path == '/robots.txt':
                    return httpx.Response(302, headers={'Location': '/index.html'})
                return httpx.Response(200, content=b'<!DOCTYPE HTML><html><body>Publisher home</body></html>')
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                fetcher = PublisherHTTP(client, 'landspace')
                await fetcher.check_robots()
                self.assertEqual(fetcher.robots_state, 'html_response_no_rules')
                self.assertEqual(visited, ['/robots.txt', '/index.html'])
                with self.assertRaises(ValueError):
                    await fetcher.get('https://www.landspace.com/index.html')
        with patch('backend.html_sources.DETAIL_DELAY', 0): asyncio.run(run())

    def fake_client(self, failure=False):
        source = 'cmse'
        listing = (FIXTURES / source / 'list.html').read_text(encoding='utf-8').replace('countPage = 34', 'countPage = 2')
        def respond(request):
            if request.url.path == '/robots.txt':
                return httpx.Response(404)
            if request.url.path.endswith(('zhxw/', 'index_1.html')):
                return httpx.Response(200, text=listing)
            if failure:
                return httpx.Response(429, headers={'Retry-After': '60'})
            return httpx.Response(200, content=(FIXTURES / source / 'detail-0.html').read_bytes())
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    def test_backfill_budget_queue_resume_and_timestamp_preservation(self):
        async def run():
            async with self.fake_client() as client:
                result = await backfill.execute('cmse', max_articles=2, client=client)
                self.assertEqual(result['status'], 'paused_budget')
                self.assertEqual(result['counts']['stored'], 2)
                self.assertGreater(result['counts']['pending'], 0)
                run_id = result['id']
                before = [(row['id'], row['first_seen_at']) for row in news.list_articles(source='cmse')['items']]
                result = await backfill.execute('cmse', resume=run_id, max_articles=100, client=client)
                self.assertEqual(result['status'], 'enumerated_complete')
                self.assertEqual(result['counts']['stored'], 15)
                after = {(row['id'], row['first_seen_at']) for row in news.list_articles(source='cmse')['items']}
                self.assertTrue(set(before) <= after)
                self.assertIsNone(news.source_state('cmse')['last_success_at'])
                again = await backfill.execute('cmse', resume=run_id, client=client)
                self.assertEqual(again['counts']['stored'], 15)
        with patch('backend.html_sources.DETAIL_DELAY', 0):
            asyncio.run(run())

    def test_backfill_dry_run_and_retry_after(self):
        async def run():
            async with self.fake_client() as client:
                result = await backfill.execute('cmse', dry_run=True, max_articles=2, client=client)
                self.assertEqual(result['status'], 'dry_run')
                self.assertEqual(news.list_articles()['items'], [])
                with news.connect() as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM backfill_runs').fetchone()[0], 0)
            async with self.fake_client(failure=True) as client:
                result = await backfill.execute('cmse', client=client)
                self.assertEqual(result['status'], 'paused_throttle')
                self.assertTrue(news.source_state('cmse')['retry_after_at'])
        with patch('backend.html_sources.DETAIL_DELAY', 0):
            asyncio.run(run())

    def test_resume_can_reparse_undated_without_replacing_existing_ids(self):
        news.store_records(self.records('cmse'))
        original = {(row['id'], row['first_seen_at']) for row in news.list_articles(source='cmse')['items']}
        listing = (FIXTURES / 'cmse' / 'list.html').read_text(encoding='utf-8').replace('countPage = 34', 'countPage = 2')
        raw = (FIXTURES / 'cmse' / 'detail-0.html').read_text(encoding='utf-8')
        def missing_date(request):
            if request.url.path == '/robots.txt': return httpx.Response(404)
            if request.url.path.endswith(('zhxw/', 'index_1.html')): return httpx.Response(200, text=listing)
            return httpx.Response(200, text=raw.replace('2026-08-28', '未提供'))
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(missing_date)) as client:
                first = await backfill.execute('cmse', max_articles=100, client=client)
                self.assertEqual(first['status'], 'enumerated_with_gaps')
                self.assertEqual(first['counts']['undated'], 15)
            async with self.fake_client() as client:
                resumed = await backfill.execute('cmse', resume=first['id'], retry_undated=True, max_articles=100, client=client)
                self.assertEqual(resumed['id'], first['id'])
                self.assertEqual(resumed['status'], 'enumerated_complete')
                self.assertEqual(resumed['counts']['stored'], 15)
                self.assertNotIn('undated', resumed['counts'])
                current = {(row['id'], row['first_seen_at']) for row in news.list_articles(source='cmse')['items']}
                self.assertTrue(original <= current)
        with patch('backend.html_sources.DETAIL_DELAY', 0): asyncio.run(run())

    def test_permanent_failed_url_does_not_starve_pending_on_resume(self):
        async def run():
            base = self.fake_client()
            listing = (FIXTURES / 'cmse' / 'list.html').read_text(encoding='utf-8').replace('countPage = 34', 'countPage = 2')
            items, _ = parse_listing('cmse', listing, news.SOURCES['cmse']['url'])
            bad_path = httpx.URL(items[0]['url']).path
            def respond(request):
                if request.url.path == '/robots.txt': return httpx.Response(404)
                if request.url.path.endswith(('zhxw/', 'index_1.html')): return httpx.Response(200, text=listing)
                if request.url.path == bad_path: return httpx.Response(404)
                return httpx.Response(200, content=(FIXTURES / 'cmse' / 'detail-0.html').read_bytes())
            await base.aclose()
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                first = await backfill.execute('cmse', max_articles=1, client=client)
                self.assertEqual(first['counts'].get('failed'), 1)
                second = await backfill.execute('cmse', resume=first['id'], max_articles=1, client=client)
                self.assertEqual(second['counts'].get('stored'), 1)
                self.assertEqual(second['counts'].get('failed'), 1)
        with patch('backend.html_sources.DETAIL_DELAY', 0): asyncio.run(run())

    def test_request_delay_is_inside_time_budget(self):
        async def respond(request):
            await asyncio.sleep(2)
            return httpx.Response(404)
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                result = await backfill.execute('cmse', max_seconds=1, client=client)
                self.assertEqual(result['status'], 'paused_budget')
                self.assertLess(result['batch']['seconds'], 1.5)
        asyncio.run(run())

    def test_all_detail_failures_are_failed_not_partial(self):
        async def run():
            async with self.fake_client(failure=True) as client:
                result = await collect_html(client, 'cmse')
                self.assertEqual(result['result'], 'failed')
                self.assertEqual(news.source_state('cmse')['last_result'], 'failed')
                self.assertIsNone(news.source_state('cmse')['last_success_at'])
        with patch('backend.html_sources.DETAIL_DELAY', 0): asyncio.run(run())


class MigrationTests(unittest.TestCase):
    def test_legacy_database_repeated_migration_and_consistent_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite3'
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript('''CREATE TABLE sources (id TEXT PRIMARY KEY,name TEXT NOT NULL,feed_url TEXT NOT NULL,
                  last_attempt_at TEXT,last_success_at TEXT,last_error TEXT,etag TEXT,last_modified TEXT,last_item_count INTEGER DEFAULT 0);
                  CREATE TABLE articles (id INTEGER PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),source_item_id TEXT,
                  canonical_url TEXT NOT NULL,original_url TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,published_at TEXT,
                  date_status TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,content_hash TEXT NOT NULL,
                  lang TEXT NOT NULL DEFAULT 'en',material_status TEXT NOT NULL DEFAULT 'summary_only',UNIQUE(source_id,canonical_url));
                  INSERT INTO sources(id,name,feed_url) VALUES('nasa','NASA','https://www.nasa.gov/news-release/feed/');
                  INSERT INTO articles(id,source_id,canonical_url,original_url,title,summary,date_status,first_seen_at,last_seen_at,content_hash)
                  VALUES(47,'nasa','https://www.nasa.gov/a','https://www.nasa.gov/a','Original','Summary','missing','original-first','original-last','hash');''')
            with patch.object(news, 'DB_PATH', path):
                news.initialize()
                news.initialize()
                row = news.list_articles()['items'][0]
                self.assertEqual((row['id'], row['canonical_url'], row['first_seen_at']), (47, 'https://www.nasa.gov/a', 'original-first'))
                self.assertEqual(row['lang'], 'und')
                self.assertEqual(row['published_precision'], 'missing')
                with closing(sqlite3.connect(path.with_name(path.name + '.before-v2.sqlite3'))) as backup:
                    self.assertEqual(backup.execute('SELECT id,first_seen_at FROM articles').fetchone(), (47, 'original-first'))
