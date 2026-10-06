import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import news
from backend.app import app


def rss(domain="nasa.gov", title="Original", date="Mon, 05 Oct 2026 10:00:00 GMT", query="id=1"):
    return f'''<rss version="2.0"><channel><title>test</title><link>https://{domain}/</link>
    <description>test</description><item><title>{title}</title><link>https://www.{domain}/Article?{query}</link>
    <guid>one</guid><pubDate>{date}</pubDate><description><![CDATA[<p>Real summary</p><script>untrusted()</script>]]></description>
    </item></channel></rss>'''.encode()


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name) / "news.db"
        news.initialize()

    def tearDown(self):
        news.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_canonical_preserves_identity(self):
        self.assertEqual(news.canonical_url('https://NASA.gov/Article?id=1&utm_source=test'),
                         'https://nasa.gov/Article?id=1')
        self.assertNotEqual(news.canonical_url('https://nasa.gov/Article?id=1'),
                            news.canonical_url('https://nasa.gov/Article?id=2'))
        self.assertNotEqual(news.canonical_url('http://nasa.gov/Article'), news.canonical_url('https://nasa.gov/Article'))

    def test_rejects_unapproved_links(self):
        for url in ['https://nasa.gov.evil.test/x', 'http://127.0.0.1/x', 'javascript:alert(1)', 'https://user@nasa.gov/x']:
            self.assertFalse(news.allowed_url(url, 'nasa.gov'))
        with self.assertRaises(ValueError):
            news.parse_feed('nasa', rss(domain='evil.test'))

    def test_summary_is_plain_text(self):
        records, _ = news.parse_feed('nasa', rss())
        self.assertEqual(records[0]['summary'], 'Real summary')

    def test_idempotent_and_updates(self):
        records, _ = news.parse_feed('nasa', rss())
        news.store_records(records)
        records, _ = news.parse_feed('nasa', rss(title='Updated'))
        news.store_records(records)
        result = news.list_articles()
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['title'], 'Updated')

    def test_missing_date_is_not_fetch_time(self):
        records, _ = news.parse_feed('nasa', rss(date='not a date'))
        self.assertIsNone(records[0]['published_at'])
        news.store_records(records)
        self.assertIsNotNone(news.list_articles()['items'][0]['first_seen_at'])

    def test_source_failure_preserves_existing_data(self):
        records, _ = news.parse_feed('nasa', rss())
        news.store_records(records)
        news.update_source('nasa', error='timeout')
        self.assertEqual(len(news.list_articles()['items']), 1)
        self.assertEqual(news.source_state('nasa')['last_error'], 'timeout')

    def test_cursor_pagination_and_filter_binding(self):
        for i in range(5):
            records, _ = news.parse_feed('nasa', rss(query=f'id={i}'))
            news.store_records(records)
        seen, cursor = [], None
        for _ in range(3):
            result = news.list_articles(cursor=cursor, limit=2)
            seen.extend(item['id'] for item in result['items'])
            cursor = result['next_cursor']
        self.assertEqual(len(set(seen)), 5)
        self.assertIsNone(cursor)
        cursor = news.list_articles(limit=2)['next_cursor']
        with self.assertRaises(ValueError):
            news.list_articles(source='nasa', cursor=cursor)

    def test_unapproved_redirect_is_not_followed(self):
        async def run():
            transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}))
            async with httpx.AsyncClient(transport=transport) as client:
                with self.assertRaises(ValueError):
                    await news.fetch_feed(client, 'nasa', {})
        asyncio.run(run())

    def test_sources_are_isolated(self):
        async def run():
            def response(req):
                return httpx.Response(503) if 'nasa.gov' in req.url.host else httpx.Response(200, content=rss('esa.int'))
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
                result = await asyncio.gather(news.collect_source(client, 'nasa'), news.collect_source(client, 'esa'))
            self.assertIn('error', result[0])
            self.assertEqual(result[1]['accepted'], 1)
            self.assertEqual(len(news.list_articles()['items']), 1)
        asyncio.run(run())

    def test_api_limits_details_and_cursor(self):
        records, _ = news.parse_feed('nasa', rss())
        news.store_records(records)
        with patch.dict(os.environ, {'COLLECT_ENABLED': '0'}), TestClient(app) as client:
            self.assertEqual(client.get('/api/health').json()['articles'], 1)
            self.assertEqual(client.get('/api/news?source=unknown').status_code, 400)
            self.assertEqual(client.get('/api/news?limit=999').status_code, 422)
            self.assertEqual(client.get('/api/news?cursor=broken').status_code, 400)
            self.assertEqual(client.get('/api/news/999').status_code, 404)
            self.assertEqual(client.get('/api/news/1').json()['material_status'], 'summary_only')
            self.assertEqual(client.get('/').status_code, 200)

    def test_numbered_pages_counts_clamping_and_empty_filters(self):
        for number in range(45):
            news.store_records(news.parse_feed('nasa', rss(query=f'id={number}'))[0])
        first = news.list_articles(page=1, page_size=20)
        second = news.list_articles(page=2, page_size=20, snapshot=first['snapshot'])
        last = news.list_articles(page=999, page_size=20, snapshot=first['snapshot'])
        self.assertEqual((first['total'], first['total_pages']), (45, 3))
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(last['page'], 3)
        self.assertEqual(len(last['items']), 5)
        ids = [row['id'] for data in (first, second, last) for row in data['items']]
        self.assertEqual(len(set(ids)), 45)
        empty = news.list_articles(source='esa', page=5, page_size=10)
        self.assertEqual((empty['items'],empty['total'],empty['page'],empty['total_pages']), ([],0,1,1))

    def test_numbered_snapshot_excludes_new_articles_until_refresh(self):
        for number in range(12):
            news.store_records(news.parse_feed('nasa', rss(query=f'id={number}'))[0])
        first = news.list_articles(source='nasa', page=1, page_size=10)
        news.store_records(news.parse_feed('nasa', rss(query='id=new'))[0])
        second = news.list_articles(source='nasa', page=2, page_size=10, snapshot=first['snapshot'])
        self.assertEqual(second['total'], 12)
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
        self.assertEqual(news.list_articles(source='nasa', page=1, page_size=10)['total'], 13)

    def test_numbered_page_api_preserves_filter_and_cursor_contracts(self):
        news.store_records(news.parse_feed('nasa', rss())[0])
        news.store_records(news.parse_feed('esa', rss(domain='esa.int'))[0])
        with patch.dict(os.environ, {'COLLECT_ENABLED':'0'}), TestClient(app) as client:
            response = client.get('/api/news?page=1&page_size=10&source=nasa&category=international_agency&geographic_region=north_america')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['total'], 1)
            self.assertEqual(response.json()['page_size'], 10)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(client.get('/api/news?page=0').status_code, 422)
            self.assertEqual(client.get('/api/news?page=1&page_size=100').status_code, 422)
            self.assertEqual(client.get('/api/news?page=1&cursor=broken').status_code, 400)
            self.assertEqual(client.get('/api/news?snapshot=0').status_code, 400)
            self.assertIn('next_cursor', client.get('/api/news?limit=1').json())


if __name__ == '__main__':
    unittest.main()
