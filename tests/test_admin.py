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

    def prepare(self):
        self.login()
        result = self.post('/api/articles/1/draft', {'revision': 0, 'document': edition()})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['revision']

    def approve(self, revision):
        result = self.post('/api/articles/1/approve', {'revision': revision, 'license_checked': True, 'complete_checked': True})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_auth_csrf_logout_and_no_public_admin_routes(self):
        self.assertEqual(self.admin.get('/api/articles').status_code, 401)
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

    def test_draft_not_public_approval_atomic_and_stale_revision_rejected(self):
        revision = self.prepare()
        self.assertEqual(self.public.get('/api/news/1/content').json()['blocks'], [])
        self.assertEqual(self.post('/api/articles/1/approve', {'revision': revision}).status_code, 409)
        self.assertEqual(self.post('/api/articles/1/draft', {'revision': 0, 'document': edition()}).status_code, 409)
        self.approve(revision)
        self.assertEqual(self.public.get('/api/news/1/content').json()['reading_mode'], 'full_text')
        self.assertEqual(self.post('/api/articles/1/approve', {'revision': revision, 'license_checked': True, 'complete_checked': True}).status_code, 409)
        detail = self.admin.get('/api/articles/1').json()
        self.assertEqual(detail['document']['reviewer'], 'admin')
        self.assertEqual(self.post('/api/articles/1/withdraw', {'reason': 'license withdrawn'}).status_code, 200)
        self.assertEqual(self.public.get('/api/news/1/content').json()['blocks'], [])

    def test_link_only_source_cannot_be_approved(self):
        news.store_records(news.parse_feed('esa', rss(domain='esa.int'))[0])
        self.login()
        self.assertEqual(self.post('/api/articles/2/draft', {'revision': 0, 'document': edition(url='https://www.esa.int/Article?id=1')}).status_code, 409)
        self.assertEqual(self.post('/api/articles/2/capture', {'revision': 0}).status_code, 409)

    def test_capture_job_never_authorizes_and_conflict_retains_edits(self):
        self.login()
        result = self.post('/api/articles/1/capture', {'revision': 0})
        self.assertEqual(result.status_code, 200)
        document = edition(); document['permissions']['text'] = {'status': 'pending'}
        with patch('backend.review_capture.capture', return_value=(document, [])):
            review_worker.run_one()
        self.assertEqual(self.public.get('/api/news/1/content').json()['blocks'], [])
        detail = self.admin.get('/api/articles/1').json()
        self.assertEqual(detail['jobs'][0]['state'], 'done')
        self.post('/api/articles/1/capture', {'revision': detail['revision']})
        newer = edition(); newer['blocks'][0]['text'] = 'Manual edits survive late capture'
        self.post('/api/articles/1/draft', {'revision': detail['revision'], 'document': newer})
        with patch('backend.review_capture.capture', return_value=(document, [])):
            review_worker.run_one()
        detail = self.admin.get('/api/articles/1').json()
        self.assertEqual(detail['document']['blocks'][0]['text'], newer['blocks'][0]['text'])
        self.assertEqual(detail['jobs'][0]['state'], 'failed')

    def test_local_image_validation_delivery_withdrawal_and_recreation(self):
        revision = self.prepare(); result = self.approve(revision)
        image_url = 'https://www.nasa.gov/wp-content/uploads/2026/10/test.png'
        with news.connect() as conn:
            conn.execute('UPDATE review_drafts SET candidates=? WHERE article_id=1', (json.dumps([{'source_url': image_url, 'caption': 'Source caption', 'block_index': 1}]),))
        detail = self.admin.get('/api/articles/1').json()
        permission = {'status': 'explicit_grant', 'basis': 'Isolated own test image', 'rightsholder': 'Test author', 'purpose': 'public_web_image', 'third_party_check': 'None'}
        payload = {'revision': detail['revision'], 'source_url': image_url, 'block_index': 1, 'position_checked': True, 'caption': 'Reviewed caption', 'credit': 'Test author', 'permission': permission}
        self.assertEqual(self.post('/api/articles/1/images', {**payload, 'block_index': 1000}).status_code, 409)
        self.assertEqual(self.post('/api/articles/1/images', {**payload, 'source_url': 'http://127.0.0.1/x.png'}).status_code, 409)
        job = self.post('/api/articles/1/images', payload)
        self.assertEqual(job.status_code, 200, job.text)
        buffer = BytesIO(); Image.new('RGB', (20, 10), 'red').save(buffer, 'PNG'); raw = buffer.getvalue()
        with patch.object(publisher_fetch.Publisher, 'get', return_value=(raw, 'image/png')):
            review_worker.run_one()
        content = self.public.get('/api/news/1/content').json()
        self.assertEqual(len(content['assets']), 1)
        asset = content['assets'][0]
        response = self.public.get(asset['url'])
        self.assertEqual(response.status_code, 200); self.assertEqual(response.content, raw)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('object_key', content['assets'][0])
        from tools import backup_review
        manifest = backup_review.backup(news.DB_PATH, Path(self.temp.name)/'snapshot')
        self.assertEqual(len(manifest['images']), 1)
        destination = Path(self.temp.name)/'restored'
        backup_review.restore(Path(self.temp.name)/'snapshot', destination)
        live = news.DB_PATH
        try:
            news.DB_PATH = destination/'news.sqlite3'
            news.initialize()
            self.assertEqual(self.public.get(asset['url']).content, raw)
            self.assertEqual(self.public.get('/api/news/1/content').json(), content)
        finally:
            news.DB_PATH = live
        news.initialize()
        self.assertEqual(self.public.get(asset['url']).content, raw)
        self.assertEqual(self.post('/api/assets/'+asset['id']+'/withdraw', {'reason': 'image withdrawn'}).status_code, 200)
        self.assertEqual(self.public.get(asset['url']).status_code, 404)
        withdrawn = self.public.get('/api/news/1/content').json()
        self.assertEqual(withdrawn['assets'], [])
        self.assertNotEqual(content['content_version'], withdrawn['content_version'])

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


if __name__ == '__main__':
    unittest.main()
