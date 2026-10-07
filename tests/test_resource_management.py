"""Shared directory persistence, auth, revision conflicts and offline HEAD behavior."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import admin_auth, news, resources, management_store as store, resource_admin
from backend.app import app as public_app
from backend.admin_app import app as admin_app

ORIGIN = 'http://127.0.0.1:18080'


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_db, self.old_items = news.DB_PATH, resources.catalog.items
        news.DB_PATH = root / 'news.sqlite3'
        self.source = root / 'resources.json'
        self.items = [dict(id='book-first', title='原始书名', object_key='public/中文 100%.pdf',
                           size_bytes=100, published=True, display_order=2, authors=['原作者'],
                           edition='保留版本', description='保留旧元信息', cover_key='public/covers/old.jpg')]
        self.source.write_text(json.dumps(self.items), encoding='utf-8')
        self.env = patch.dict(os.environ, {'MANAGEMENT_DB_PATH': str(root / 'site-management.sqlite3'),
            'RESOURCES_PATH': str(self.source), 'RESOURCE_OSS_ORIGIN': resources.OSS_ORIGIN,
            'ADMIN_ORIGIN': ORIGIN, 'COLLECT_ENABLED': '0', 'REVIEW_WORKER_ENABLED': '0', 'AI_ENABLED': '0'})
        self.env.start()
        news.initialize(); admin_auth.initialize_user('admin', 'resource-password-2026')
        self.admin = TestClient(admin_app, base_url=ORIGIN)
        self.public = TestClient(public_app)
        self.admin.__enter__(); self.public.__enter__()
        self.headers = {'Origin': ORIGIN}

    def tearDown(self):
        self.admin.__exit__(None, None, None); self.public.__exit__(None, None, None)
        self.env.stop(); news.DB_PATH = self.old_db; resources.catalog.items = self.old_items
        self.temp.cleanup()

    def login(self):
        result = self.admin.post('/api/login', json={'username':'admin', 'password':'resource-password-2026'}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.headers['X-CSRF-Token'] = result.json()['csrf']

    def update(self, revision=1, changes=None):
        return self.admin.patch('/api/resources/book-first', json={'revision':revision, 'changes':changes or {'title':'更新书名'}}, headers=self.headers)

    def migrate(self):
        return store.migrate(self.source)

    def test_auth_csrf_origin_and_public_write_routes(self):
        self.migrate()
        self.assertEqual(self.admin.get('/api/resources').status_code, 401)
        self.assertEqual(self.admin.get('/api/resources/book-first/history').status_code, 401)
        self.assertEqual(self.admin.post('/api/resources', json={}).status_code, 401)
        self.assertEqual(self.public.patch('/api/resources/book-first', json={}).status_code, 405)
        self.login()
        self.assertEqual(self.admin.patch('/api/resources/book-first', json={}, headers={'Origin':ORIGIN}).status_code, 403)
        self.assertEqual(self.admin.patch('/api/resources/book-first', json={}, headers={**self.headers, 'Origin':'https://evil.test'}).status_code, 403)
        self.assertEqual(self.update().status_code, 200)

    def test_explicit_migration_preserves_metadata_and_reimport_never_overwrites(self):
        self.login()
        self.assertEqual(self.admin.get('/api/resources').status_code, 503)
        self.assertFalse(store.path().exists())
        self.assertEqual(self.public.get('/api/resources').json()['total'], 1)
        self.assertTrue(self.migrate()['imported'])
        self.assertEqual(self.update(changes={'title':'修改后', 'display_order':0}).status_code, 200)
        report = self.migrate()
        self.assertFalse(report['imported'])
        item = self.admin.get('/api/resources/book-first').json()
        self.assertEqual((item['title'], item['display_order'], item['revision']), ('修改后', 0, 2))
        self.assertEqual((item['edition'], item['description'], item['cover_key']), ('保留版本','保留旧元信息','public/covers/old.jpg'))
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM management_audit').fetchone()[0], 2)

    def test_atomic_invalid_migration_and_unique_paths(self):
        self.source.write_text(json.dumps(self.items * 2), encoding='utf-8')
        with self.assertRaises(store.ManagementError): self.migrate()
        self.assertFalse(store.path().exists())
        self.source.write_text(json.dumps(self.items), encoding='utf-8'); self.migrate(); self.login()
        result = self.admin.post('/api/resources', json={'changes':{'title':'重复', 'pdf_address':self.items[0]['object_key'], 'size_bytes':10}}, headers=self.headers)
        self.assertEqual(result.status_code, 409)
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM resource_items').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM resource_revisions').fetchone()[0], 1)

    def test_live_download_hide_restore_and_conflicting_edits(self):
        self.migrate(); self.login()
        self.assertEqual(self.update(changes={'pdf_address':resources.OSS_ORIGIN+'/public/new%20%E4%B9%A6.pdf'}).status_code, 200)
        response = self.public.get('/api/resources/book-first/download', follow_redirects=False)
        self.assertEqual(response.headers['location'], resources.OSS_ORIGIN+'/public/new%20%E4%B9%A6.pdf')
        self.assertEqual(self.update(changes={'title':'并发覆盖'}).status_code, 409)
        self.assertEqual(self.update(2, {'published':False}).status_code, 200)
        self.assertEqual(self.public.get('/api/resources').json()['total'], 0)
        self.assertEqual(self.public.get('/api/resources/book-first/download').status_code, 404)
        result = self.admin.post('/api/resources/book-first/restore', json={'revision':3, 'target_revision':1}, headers=self.headers)
        self.assertEqual(result.json()['revision'], 4)
        self.assertEqual(self.public.get('/api/resources').json()['items'][0]['title'], '原始书名')
        self.assertEqual(len(self.admin.get('/api/resources/book-first/history').json()['items']), 4)
        resources.catalog.items = None
        self.assertEqual(self.public.get('/api/resources').json()['total'], 1)

    def test_missing_and_corrupt_active_database_never_fall_back_to_json(self):
        self.migrate()
        # Checkpoint before moving the database, so the test does not depend on open WAL handles.
        with closing(sqlite3.connect(store.path())) as db: db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        store.path().rename(store.path().with_suffix('.saved'))
        self.assertEqual(self.public.get('/api/resources').status_code, 503)
        self.assertEqual(self.public.get('/api/health').status_code, 200)
        with self.assertRaises(store.ManagementError): self.migrate()
        store.path().write_bytes(b'broken database')
        self.assertEqual(self.public.get('/api/resources').status_code, 503)

    def test_new_default_hidden_field_validation_and_existing_cover_choices(self):
        self.migrate(); self.login()
        values = {'title':'新资料', 'pdf_address':'public/new.pdf', 'size_bytes':20, 'cover_asset':None}
        result = self.admin.post('/api/resources', json={'changes':values}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()['published'])
        self.assertEqual(self.public.get('/api/resources/'+result.json()['id']+'/download').status_code, 404)
        for changes in ({'title':' '}, {'size_bytes':True}, {'published':'false'}, {'display_order':-1},
                        {'id':'changed'}, {'cover_asset':'../cover.jpg'}, {'cover_asset':'missing-cover.jpg'}):
            self.assertEqual(self.update(changes=changes).status_code, 400, changes)
        self.assertEqual(self.admin.get('/api/resources?state=hidden').json()['items'][0]['id'], result.json()['id'])

    def test_pdf_url_normalization_and_rejections(self):
        self.assertEqual(resource_admin.pdf_key(resources.OSS_ORIGIN+'/public/%E4%B8%AD%E6%96%87%20100%25.pdf'), 'public/中文 100%.pdf')
        self.assertEqual(resource_admin.pdf_key('public/中文 100%.pdf'), 'public/中文 100%.pdf')
        for value in ('https://evil.test/public/a.pdf', resources.OSS_ORIGIN+':443/public/a.pdf',
                      resources.OSS_ORIGIN+'/public/a.pdf?signature=x', resources.OSS_ORIGIN+'/public/a.pdf#x',
                      resources.OSS_ORIGIN+'/public/%2e%2e/a.pdf', resources.OSS_ORIGIN+'/public/%ff.pdf',
                      resources.OSS_ORIGIN+'/public/%ZZ.pdf', 'public/../x.pdf', 'public/a.txt',
                      'public/a.pdf?x=1', 'public/\\x.pdf', 'public/covers/a.pdf', 'public/a\x00.pdf'):
            with self.assertRaises(store.ManagementError, msg=value): resource_admin.pdf_key(value)

    def test_offline_head_limits_no_redirects_and_size_not_silently_changed(self):
        self.migrate(); self.login()
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, headers={'content-length':'321'})
        original = httpx.AsyncClient
        def fake(**kwargs):
            self.assertFalse(kwargs['follow_redirects']); self.assertFalse(kwargs['trust_env'])
            return original(**kwargs, transport=httpx.MockTransport(handle))
        with patch('backend.resource_admin.httpx.AsyncClient', side_effect=fake):
            result = self.admin.post('/api/resources/book-first/check', json={'revision':1}, headers=self.headers)
            self.assertEqual(result.json()['size_bytes'], 321)
            self.assertEqual(result.json()['state'], 'accessible')
            self.assertEqual(requests[0].method, 'HEAD')
            self.assertEqual(self.admin.post('/api/resources/book-first/check', json={'revision':1}, headers=self.headers).status_code, 429)
        self.assertEqual(self.admin.get('/api/resources/book-first').json()['size_bytes'], 100)
        for code in (302, 403, 405, 404):
            with store.connection(write=True) as db: db.execute('DELETE FROM resource_checks')
            with patch('backend.resource_admin.httpx.AsyncClient', side_effect=lambda **kw: original(**kw, transport=httpx.MockTransport(lambda req: httpx.Response(code, headers={'location':'https://evil.test'})))):
                result = self.admin.post('/api/resources/book-first/check', json={'revision':1}, headers=self.headers).json()
            self.assertEqual(result['state'], 'missing' if code == 404 else 'unconfirmed')

    def test_real_catalog_migration_cli_backup_and_legacy_export(self):
        catalog_path = resources.ROOT / 'content/resources.json'
        original = json.loads(catalog_path.read_text(encoding='utf-8'))
        self.assertEqual(len(original), 28)
        report = store.migrate(catalog_path)
        self.assertEqual(report['current_count'], 28)
        with store.connection() as db:
            saved = {row['id']: json.loads(row['record']) for row in db.execute('SELECT id,record FROM resource_items')}
        self.assertEqual(saved, {item['id']:resources.Resource.model_validate(item).model_dump() for item in original})
        root = Path(self.temp.name)
        for mode, destination in [('backup', root / 'backup.sqlite3'), ('export', root / 'legacy.json')]:
            result = subprocess.run([sys.executable, str(resources.ROOT / 'tools/resources_manage.py'), mode,
                                     '--output', str(destination)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Refusing an existing destination protects previously collected backups.
            repeated = subprocess.run([sys.executable, str(resources.ROOT / 'tools/resources_manage.py'), mode,
                                       '--output', str(destination)], capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
        with closing(sqlite3.connect(root / 'backup.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM resource_items').fetchone()[0], 28)
        exported = json.loads((root / 'legacy.json').read_text(encoding='utf-8'))
        self.assertEqual({item['id']:item for item in exported}, saved)

    def test_restore_conflict_invalid_schema_and_global_head_budget(self):
        self.migrate(); self.login(); self.update()
        conflict = self.admin.post('/api/resources/book-first/restore', json={'revision':1, 'target_revision':1}, headers=self.headers)
        self.assertEqual(conflict.status_code, 409)
        with store.connection(write=True) as db:
            import time
            db.executemany('INSERT INTO resource_checks(resource_id,checked_at) VALUES(?,?)', [('other',time.time())]*10)
        with patch('backend.resource_admin.httpx.AsyncClient', side_effect=AssertionError('must not call upstream')):
            self.assertEqual(self.admin.post('/api/resources/book-first/check', json={'revision':2}, headers=self.headers).status_code, 429)
        with store.connection(write=True) as db: db.execute('DELETE FROM schema_meta')
        self.assertEqual(self.public.get('/api/resources').status_code, 503)


if __name__ == '__main__': unittest.main()
