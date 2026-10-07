"""Private review auth, manual publication, source gate and durable local images."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from backend import news, reading, admin_auth, review_store, review_worker, news_assets, news_image_store, publisher_fetch
from backend.app import app as public_app
from backend.admin_app import app as admin_app
from test_news import rss
from test_reading import edition

ORIGIN = 'http://127.0.0.1:18080'


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name)/'news.sqlite3'
        news.initialize()
        news.store_records(news.parse_feed('nasa', rss())[0])
        admin_auth.initialize_user('admin', 'correct-password-2026')
        self.environment = patch.dict(os.environ, {'ADMIN_ORIGIN': ORIGIN, 'REVIEW_WORKER_ENABLED': '0', 'COLLECT_ENABLED': '0'})
        self.environment.start()
        self.admin = TestClient(admin_app, base_url=ORIGIN)
        self.public = TestClient(public_app)
        self.admin.__enter__(); self.public.__enter__()
        self.csrf = ''


    def tearDown(self):
        self.admin.__exit__(None, None, None); self.public.__exit__(None, None, None)
        self.environment.stop(); news.DB_PATH = self.old_db; self.temp.cleanup()


    def login(self):
        result = self.admin.post('/api/login', json={'username': 'admin', 'password': 'correct-password-2026'}, headers={'Origin': ORIGIN})
        self.assertEqual(result.status_code, 200, result.text)
        self.csrf = result.json()['csrf']
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        self.assertIn('SameSite=strict', result.headers['set-cookie'])


    def post(self, path, data):
        return self.admin.post(path, json=data, headers={'Origin': ORIGIN, 'X-CSRF-Token': self.csrf})


    def test_auth_csrf_logout_and_no_public_admin_routes(self):
        self.assertEqual(self.admin.get('/api/session').status_code, 401)
        self.assertEqual(self.public.get('/api/session').status_code, 404)
        self.assertEqual(self.public.get('/admin').status_code, 404)
        self.assertEqual(self.admin.post('/api/login', json={}, headers={'Origin': 'http://evil.invalid'}).status_code, 403)
        self.login()
        self.assertEqual(self.admin.post('/api/logout', json={}, headers={'Origin': ORIGIN}).status_code, 403)
        self.assertEqual(self.post('/api/logout', {}).status_code, 200)
        self.assertEqual(self.admin.get('/api/session').status_code, 401)


    def test_persistent_lockout_and_password_never_stored_plain(self):
        for _ in range(5):
            self.assertEqual(self.admin.post('/api/login', json={'username': 'admin', 'password': 'bad'}, headers={'Origin': ORIGIN}).status_code, 401)
        self.assertEqual(self.admin.post('/api/login', json={'username': 'admin', 'password': 'correct-password-2026'}, headers={'Origin': ORIGIN}).status_code, 429)
        with news.connect() as conn:
            user = conn.execute('SELECT * FROM admin_user').fetchone()
            self.assertNotIn('correct-password', user['password_hash'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_sessions').fetchone()[0], 0)


    def test_image_budgets_and_ssrf_guards(self):
        for url in ('http://127.0.0.1/x', 'http://www.nasa.gov@127.0.0.1/x', 'https://www.nasa.gov/wp-content/uploads/../x.png'):
            with self.assertRaises(ValueError):
                publisher_fetch.checked_url('nasa', url, image=True)
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 443))]), self.assertRaises(ValueError):
            publisher_fetch.public_addresses('www.nasa.gov', 443)
        with self.assertRaises(ValueError):
            news_image_store.path('../../etc/passwd')
        with self.assertRaises(Exception):
            news_assets.inspect_image(b'<svg></svg>', 'image/png')
        with self.assertRaises(ValueError):
            news_assets.inspect_image(b'x'*(8*1024*1024+1), 'image/jpeg')


    def test_request_limits_and_admin_no_store(self):
        self.assertEqual(self.admin.post('/api/login', json=[]).status_code, 400)
        self.assertEqual(self.admin.post('/api/login', content=b'x'*350001, headers={'Content-Type': 'application/json'}).status_code, 413)
        self.assertEqual(self.admin.get('/').headers['cache-control'], 'no-store')


    def test_real_nasa_capture_retains_units_but_no_permission(self):
        from backend.review_capture import parse
        raw = (Path(__file__).parent/'fixtures/nasa-review-davinci.html').read_bytes()
        document, images = parse('nasa', 'https://www.nasa.gov/image-article/nasas-davinci-probe-can-stand-the-heat/', raw, 'reviewer')
        self.assertEqual(len(document['blocks']), 5)
        self.assertIn('869 F, or 465 C', document['blocks'][1]['text'])
        self.assertEqual(document['permissions']['text']['status'], 'pending')
        self.assertTrue(images)


    def test_news_management_routes_retired_and_worker_not_started(self):
        self.login()
        for path in ('/api/articles','/api/articles/1','/api/articles/1/history'):
            self.assertEqual(self.admin.get(path).status_code,404)
        for path in ('/api/articles/1/capture','/api/articles/1/draft','/api/articles/1/approve','/api/articles/1/images','/api/assets/old/withdraw'):
            self.assertEqual(self.post(path,{}).status_code,404)
        page=self.admin.get('/').text
        self.assertNotIn('新闻审核',page)
        self.assertIn('AI 设置',page)
        with patch('backend.review_worker.loop',side_effect=AssertionError('retired worker')):
            with TestClient(admin_app): pass

    def test_existing_manual_editions_and_images_survive_backend_retirement(self):
        result=reading.publish(edition())
        with news.connect() as db:item=review_store.article(db,1)
        permission={'status':'explicit_grant','basis':'Own isolated test image','rightsholder':'Test author','purpose':'public_web_image','third_party_check':'None'}
        payload={'version':result['version'],'source_url':'https://www.nasa.gov/wp-content/uploads/2026/10/test.png','block_index':1,'caption':'Reviewed caption','credit':'Test author','permission':permission}
        buffer=BytesIO();Image.new('RGB',(20,10),'red').save(buffer,'PNG');raw=buffer.getvalue()
        with patch.object(publisher_fetch.Publisher,'get',return_value=(raw,'image/png')):
            news_assets.store_approved(item,payload,'0123456789abcdef0123456789abcdef')
        content=self.public.get('/api/news/1/content').json()
        self.assertEqual(content['reading_mode'],'full_text')
        url=content['assets'][0]['url']
        self.assertEqual(self.public.get(url).content,raw)
        from tools import backup_review
        snapshot=Path(self.temp.name)/'snapshot'
        manifest=backup_review.backup(news.DB_PATH,snapshot)
        self.assertEqual(len(manifest['images']),1)
        news.initialize()
        self.assertEqual(self.public.get(url).content,raw)
        reading.withdraw(1,'test','fixture withdrawal')
        self.assertEqual(self.public.get(url).status_code,404)

    def test_preserved_draft_store_conflicts_and_permissions(self):
        document=edition();document['permissions']['text']['status']='pending'
        revision=review_store.save_draft(1,document,0,'test')
        with self.assertRaises(ValueError):review_store.save_draft(1,document,0,'test')
        self.assertEqual(self.public.get('/api/news/1/content').json()['blocks'],[])
        self.assertEqual(revision,1)

if __name__ == '__main__':
    unittest.main()
