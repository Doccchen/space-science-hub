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


if __name__ == '__main__':
    unittest.main()
