import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import news, resources
from backend.app import app


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'resources.json'
        self.items = [dict(id=f'book-{number}', title=f'书籍 {number}', object_key=f'public/book-{number}.pdf',
                           authors=['作者A'], tags=['工程'], category='数学' if number < 8 else '电子',
                           size_bytes=1024, published=number < 15, display_order=number)
                      for number in range(16)]
        self.path.write_text(json.dumps(self.items), encoding='utf-8')
        self.old_db, self.old_catalog = news.DB_PATH, resources.catalog.items
        news.DB_PATH = Path(self.temp.name) / 'news.sqlite3'
        self.env = patch.dict(os.environ, {'COLLECT_ENABLED': '0', 'RESOURCES_PATH': str(self.path),
                                          'RESOURCE_OSS_ORIGIN': resources.OSS_ORIGIN})
        self.env.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        news.DB_PATH, resources.catalog.items = self.old_db, self.old_catalog
        self.temp.cleanup()

    def test_public_pages_are_stable_and_facets_are_not_truncated(self):
        first = self.client.get('/api/resources').json()
        second = self.client.get('/api/resources?page=2').json()
        self.assertEqual((first['total'], first['pages']), (15, 2))
        self.assertEqual([x['id'] for x in first['items']+second['items']], [f'book-{n}' for n in range(15)])
        self.assertEqual(set(first['categories']), {'数学', '电子'})
        self.assertEqual(self.client.get('/api/resources?page=999').json()['items'], [])
        for field in ('original_filename', 'object_key', 'published'):
            self.assertNotIn(field, first['items'][0])

    def test_search_normalization_author_tags_and_category(self):
        self.assertEqual(self.client.get('/api/resources', params={'q':'书籍 １'}).json()['total'], 6)
        self.assertEqual(self.client.get('/api/resources', params={'q':'作者a', 'category':'数学'}).json()['total'], 8)
        self.assertEqual(self.client.get('/api/resources', params={'q':'工程'}).json()['total'], 15)
        self.assertEqual(self.client.get('/api/resources', params={'q':'未知'}).json()['pages'], 0)

    def test_hidden_and_unknown_ids_never_download(self):
        for resource_id in ('book-15', 'unknown'):
            self.assertEqual(self.client.get('/api/resources/'+resource_id).status_code, 404)
            self.assertEqual(self.client.get('/api/resources/'+resource_id+'/download').status_code, 404)

    def test_redirect_without_network_or_pdf_reads(self):
        with patch('socket.create_connection', side_effect=AssertionError('network prohibited')), patch(
                'pathlib.Path.read_bytes', side_effect=AssertionError('PDF reads prohibited')):
            response = self.client.get('/api/resources/book-0/download?url=https://evil.test', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['location'], resources.OSS_ORIGIN+'/public/book-0.pdf')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_query_bounds(self):
        for query in ('page=0', 'page_size=49', 'page_size=0', 'q='+('x'*121), 'category='+('x'*81)):
            self.assertEqual(self.client.get('/api/resources?'+query).status_code, 422)

    def test_raw_keys_are_encoded_once_and_invalid_origins_rejected(self):
        self.assertTrue(resources.object_url('public/中文 100%.pdf').endswith('/%E4%B8%AD%E6%96%87%20100%25.pdf'))
        for key in ('../x.pdf', 'public/../x.pdf', 'public//x.pdf', 'https://evil.test/x.pdf', 'public/\\x.pdf', 'public/covers/x.pdf'):
            with self.assertRaises(ValueError):
                resources.object_url(key)
        for origin in ('http://space-hub-pub.oss-cn-chengdu.aliyuncs.com', resources.OSS_ORIGIN+'.evil.test',
                       resources.OSS_ORIGIN+'/public', resources.OSS_ORIGIN+'?x=1', 'https://user@space-hub-pub.oss-cn-chengdu.aliyuncs.com'):
            with patch.dict(os.environ, {'RESOURCE_OSS_ORIGIN': origin}), self.assertRaises(ValueError):
                resources.object_url('public/a.pdf')

    def test_invalid_catalog_isolated_from_news(self):
        for text in ('invalid json', json.dumps(self.items+[self.items[0]]), '[{"published":"false"}]'):
            self.path.write_text(text, encoding='utf-8')
            with self.assertLogs(level='ERROR'):
                resources.catalog.load()
            self.assertEqual(self.client.get('/api/resources').status_code, 503)
            self.assertEqual(self.client.get('/api/health').status_code, 200)
            self.assertEqual(self.client.get('/api/news').status_code, 200)

    def test_empty_catalog_and_detail_missing_cover(self):
        detail = self.client.get('/api/resources/book-0').json()
        self.assertIsNone(detail['cover_url'])
        self.assertIn('description', detail)
        self.path.write_text('[]', encoding='utf-8')
        resources.catalog.load()
        self.assertEqual(self.client.get('/api/resources').json()['total'], 0)

    def test_local_cover_is_scoped_and_no_introduction_needed(self):
        item = resources.Resource.model_validate({**self.items[0], 'cover_asset':'book-0.jpg'})
        result = resources.public_record(item)
        self.assertEqual(result['cover_url'], '/assets/resource-covers/book-0.jpg')
        self.assertEqual(result['description_short'], '')
        for value in ('../book-0.jpg', '/tmp/book.jpg', 'https://evil.test/x.jpg'):
            with self.assertRaises(ValueError):
                resources.Resource.model_validate({**self.items[0], 'cover_asset':value})


if __name__ == '__main__':
    unittest.main()
