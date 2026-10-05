import asyncio
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import news
from backend.app import app
from backend.html_sources import PublisherHTTP, parse_detail, parse_listing, request_allowed
from backend.publication import publication_fields

ROOT = Path(__file__).parent / 'fixtures' / 'international'
MANIFEST = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))


class InternationalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name) / 'news.sqlite3'
        news.initialize()

    def tearDown(self):
        news.DB_PATH = self.old_db
        self.temp.cleanup()

    def records(self, source):
        return [parse_detail(source, (ROOT / source / f'detail-{number}.html').read_bytes(), sample)
                for number, sample in enumerate(MANIFEST[source]['details'])]

    def test_real_lists_nine_details_and_publisher_identity(self):
        for source in MANIFEST:
            items, total = parse_listing(source, (ROOT / source / 'list.html').read_bytes(), news.SOURCES[source]['url'])
            self.assertTrue(3 <= len(items) <= 10)
            self.assertIsNone(total)
            for record in self.records(source):
                self.assertEqual(record['lang'], 'en')
                self.assertEqual(record['published_time_status'], 'provided')
                self.assertEqual(record['published_timezone'], '+0000')
                self.assertEqual(record['published_precision'], 'second')
                self.assertLessEqual(len(record['summary']), 600)
                self.assertEqual(news.SOURCES[source]['publisher_kind'], 'company')
            news.store_records(self.records(source))
            before = [(row['id'], row['first_seen_at']) for row in news.list_articles(source=source)['items']]
            news.store_records(self.records(source))
            self.assertEqual(before, [(row['id'], row['first_seen_at']) for row in news.list_articles(source=source)['items']])

    def test_redirect_alias_deduplicates_against_publisher_canonical(self):
        sample = MANIFEST['arianespace']['details'][0]
        raw = (ROOT / 'arianespace/detail-0.html').read_bytes()
        first = parse_detail('arianespace', raw, sample)
        second = parse_detail('arianespace', raw, {'url': sample['resolved_url']})
        self.assertEqual(first['canonical_url'], second['canonical_url'])
        self.assertIn('?p=', first['canonical_url'])
        news.store_records([first, second])
        self.assertEqual(len(news.list_articles()['items']), 1)

    def test_bad_links_folders_and_unverified_sources_do_not_become_news(self):
        for url in ['https://evil.test/example/', 'https://newsroom.arianespace.com/wp-content/download/a.pdf',
                    'https://newsroom.arianespace.com/section/folders/', 'https://newsroom.arianespace.com/?p=123&next=evil']:
            self.assertFalse(request_allowed('arianespace', url))
        raw = (ROOT / 'arianespace/list.html').read_text(encoding='utf-8').replace('Press Releases', 'Folders')
        with self.assertRaises(ValueError): parse_listing('arianespace', raw, news.SOURCES['arianespace']['url'])
        for source in ['spacex', 'blue_origin']:
            self.assertFalse(news.source_state(source)['enabled'])
            with self.assertRaises(ValueError): parse_listing(source, b'<html>No verified payload</html>', news.SOURCES[source]['url'])
        record = self.records('ispace')[0]
        self.assertIn('2026-09-17', record['published_at'])
        self.assertNotIn('2027', record['published_at'])

    def test_publication_precision_timezone_and_language_not_guessed(self):
        day = publication_fields('09.17.2026', date_order='mdy')
        self.assertEqual(day['published_calendar_date'], '2026-09-17')
        self.assertEqual(day['published_time_status'], 'date_only')
        self.assertIsNone(day['published_timezone'])
        european = publication_fields('17.09.2026', date_order='dmy')
        self.assertEqual(european['published_calendar_date'], '2026-09-17')
        naive = publication_fields('2026-09-17 08:30:00')
        self.assertEqual(naive['published_time_status'], 'timezone_missing')
        self.assertIsNone(naive['published_timezone'])
        aware = publication_fields('2026-09-17T00:15:00+09:00')
        self.assertEqual(aware['published_at'], '2026-09-16T15:15:00+00:00')
        self.assertEqual(aware['published_calendar_date'], '2026-09-17')
        self.assertIsNone(publication_fields(None)['published_at'])
        self.assertEqual(publication_fields('2026-02-30')['date_status'], 'invalid')
        raw = (ROOT / 'ispace/detail-0.html').read_text(encoding='utf-8')
        raw = raw.replace('en-US', '').replace('lang=""', '')
        record = parse_detail('ispace', raw, MANIFEST['ispace']['details'][0])
        self.assertEqual(record['lang'], 'und')

    def test_region_pagination_and_legacy_cursors(self):
        for source in MANIFEST: news.store_records(self.records(source))
        with patch.dict(os.environ, {'COLLECT_ENABLED': '0'}), TestClient(app) as client:
            first = client.get('/api/news?category=commercial&region=international&geographic_region=europe&limit=2').json()
            self.assertEqual(len(first['items']), 2)
            self.assertTrue(all(row['source_id'] == 'arianespace' for row in first['items']))
            cursor = first['next_cursor']
            second = client.get('/api/news', params={'category': 'commercial', 'region': 'international', 'geographic_region': 'europe', 'cursor': cursor, 'limit': 2}).json()
            self.assertEqual(len(second['items']), 1)
            self.assertEqual(client.get('/api/news', params={'category': 'commercial', 'region': 'international', 'geographic_region': 'east_asia', 'cursor': cursor}).status_code, 400)
            self.assertEqual(client.get('/api/news?region=domestic&source=ispace').status_code, 400)
            self.assertEqual(client.get('/api/news?geographic_region=unknown').status_code, 400)
            macro = client.get('/api/news?category=commercial&region=international&limit=2').json()['next_cursor']
            self.assertEqual(client.get('/api/news', params={'category':'commercial','region':'domestic','cursor':macro}).status_code, 400)
        row = news.list_articles(limit=2)['items'][-1]
        old_v2 = base64.urlsafe_b64encode(json.dumps([row['published_at'], row['id'], None, None, 2]).encode()).decode()
        self.assertTrue(news.list_articles(cursor=old_v2)['items'])
        with self.assertRaises(ValueError): news.list_articles(cursor=old_v2, region='international')
        old_agency = base64.urlsafe_b64encode(json.dumps([row['published_at'], row['id'], None, 'international_agency', 2]).encode()).decode()
        self.assertEqual(news.list_articles(cursor=old_agency, category='international_agency')['items'], [])

    def test_v3_migration_keeps_records_jobs_failures_and_enabled_flags(self):
        record = parse_detail('cnsa', (ROOT.parent / 'cnsa/detail-0.html').read_bytes(),
                              {'url':'https://www.cnsa.gov.cn/n6758823/n6758838/c10774462/content.html'})
        # Seed representative prior-run state; metadata migration is repeatable.
        news.store_records([record])
        with news.connect() as conn:
            conn.execute('UPDATE sources SET enabled=1 WHERE id=\'cnsa\'')
            conn.execute("INSERT INTO backfill_runs(id,source_id,start_at,end_at,created_at,updated_at,status) VALUES('old-run','cnsa','start','end','created','updated','paused_budget')")
            conn.execute("INSERT INTO backfill_items(run_id,url,listing,status,error) VALUES('old-run','https://www.cnsa.gov.cn/old','{}','failed','old404')")
        before = news.list_articles()['items'][0]
        with news.connect() as conn:
            for name in ['geographic_region','country_code','availability_note']:
                conn.execute(f'ALTER TABLE sources DROP COLUMN {name}')
            for name in ['published_calendar_date','published_timezone','published_time_status']:
                conn.execute(f'ALTER TABLE articles DROP COLUMN {name}')
            conn.execute('PRAGMA user_version=2')
        news.initialize(); news.initialize()
        after = news.list_articles()['items'][0]
        self.assertEqual((before['id'],before['canonical_url'],before['first_seen_at']), (after['id'],after['canonical_url'],after['first_seen_at']))
        self.assertEqual(news.source_state('cnsa')['enabled'], 1)
        self.assertEqual(after['published_calendar_date'], '2026-09-20')
        self.assertEqual(after['published_timezone'], 'Asia/Shanghai')
        self.assertEqual(news.source_state('nasa')['publisher_kind'], 'agency')
        with news.connect() as conn:
            self.assertEqual(conn.execute("SELECT status,error FROM backfill_items WHERE run_id='old-run'").fetchone()[0], 'failed')

    def test_two_hosts_have_separate_robots_and_no_external_redirect(self):
        observed = []
        def respond(request):
            observed.append((request.url.host, request.url.path))
            if request.url.path == '/robots.txt':
                return httpx.Response(200, text='User-agent: *\nDisallow:' if request.url.host.startswith('www.') else 'User-agent: *\nDisallow: /')
            return httpx.Response(200, text='Publisher sample')
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                fetcher = PublisherHTTP(client, 'arianespace')
                await fetcher.check_robots()
                with self.assertRaises(ValueError): await fetcher.get('https://newsroom.arianespace.com/?p=123')
                self.assertIn(('newsroom.arianespace.com', '/robots.txt'), observed)
                self.assertNotIn(('newsroom.arianespace.com', '/'), observed)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={'Location':'https://evil.test/news'}))) as client:
                with self.assertRaises(ValueError): await PublisherHTTP(client, 'ispace').get(news.SOURCES['ispace']['url'], robots=True)
        with patch('backend.html_sources.DETAIL_DELAY', 0): asyncio.run(run())

    def test_disabled_blocked_source_retains_history_after_access_failure(self):
        news.store_records(self.records('arianespace'))
        before = [row['id'] for row in news.list_articles()['items']]
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(403))) as client:
                result = await news.collect_source(client, 'arianespace')
                self.assertIn('error', result)
        asyncio.run(run())
        self.assertEqual([row['id'] for row in news.list_articles()['items']], before)
        self.assertTrue(news.source_state('arianespace')['last_error'])

    def test_skyroot_external_press_tab_is_not_company_owned_news(self):
        raw=(ROOT/'skyroot/list.html').read_bytes()
        self.assertIn(b'pmindia.gov.in',raw)
        for url in ['https://www.pmindia.gov.in/en/news_updates/news/', 'https://exolaunch.com/news_140',
                    'https://www.nytimes.com/2023/07/04/business/india-space-startups.html']:
            self.assertFalse(request_allowed('skyroot',url))
        with self.assertRaises(ValueError):parse_listing('skyroot',raw,news.SOURCES['skyroot']['url'])
        self.assertEqual(news.source_state('skyroot')['enabled'],0)

    def test_gilmour_oceania_and_date_published(self):
        records=self.records('gilmour');news.store_records(records)
        result=news.list_articles(category='commercial',geographic_region='oceania')
        self.assertEqual(len(result['items']),3)
        self.assertTrue(all(row['country_code']=='AU' and row['publisher_kind']=='company' for row in result['items']))
        self.assertEqual(records[0]['published_at'],'2026-09-07T23:04:14+00:00')
        self.assertEqual(records[0]['published_origin'],'detail.meta.article:published_time')

    def test_gilmour_missing_publication_does_not_use_event_date(self):
        from bs4 import BeautifulSoup
        tree=BeautifulSoup((ROOT/'gilmour/detail-0.html').read_text(encoding='utf-8'),'html.parser')
        tree.select_one('meta[property="article:published_time"]').decompose()
        for node in tree.select('script[type="application/ld+json"]'):
            value=json.loads(node.get_text());value.pop('datePublished',None);value['dateModified']='2030-01-01T00:00:00Z'
            node.string=json.dumps(value)
        record=parse_detail('gilmour',str(tree),MANIFEST['gilmour']['details'][0])
        self.assertIsNone(record['published_at'])
        self.assertEqual(record['date_status'],'missing')
