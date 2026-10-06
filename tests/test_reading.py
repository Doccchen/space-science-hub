"""Rights boundaries, immutable editions and migration of existing history."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import news, reading
from backend import reading_policy
from backend.app import app
from test_news import rss


def edition(url='https://www.nasa.gov/Article?id=1', mode='full'):
    return {'original_url': url, 'mode': mode, 'language': 'en',
            'blocks': [{'type': 'paragraph', 'text': 'Original 27 km; may launch no earlier than October.'},
                       {'type': 'heading', 'text': 'Conditions', 'level': 2},
                       {'type': 'list', 'items': ['One', 'Two']},
                       {'type': 'table', 'rows': [['Value', 'Unit'], ['27', 'km']]}],
            'permissions': {'text': {'status': 'explicit_grant', 'basis': 'Isolated test fixture, not publisher authorization',
                                    'rightsholder': 'Test author', 'purpose': 'public_web_text', 'third_party_check': 'None'},
                            'image': {'status': 'pending'}, 'translation': {'status': 'pending'}, 'ai_context': {'status': 'pending'}},
            'credit': 'Test author', 'reviewed_at': '2026-10-05T00:00:00+00:00', 'reviewer': 'test',
            'completeness': 'complete_checked' if mode == 'full' else 'own_guide_checked', 'notes': 'Isolated test only'}


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name)/'news.sqlite3'
        news.initialize()
        news.store_records(news.parse_feed('nasa', rss())[0])
        self.env = patch.dict(os.environ, {'COLLECT_ENABLED': '0'})
        self.env.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        news.DB_PATH = self.old_db
        self.temp.cleanup()

    def content(self):
        return self.client.get('/api/news/1/content').json()

    def test_default_hides_unreviewed_excerpt_but_retains_database(self):
        self.assertEqual(self.content()['read_scope'], 'link_only')
        self.assertEqual(self.content()['reading_mode'], 'link_only')
        for path in ('/api/news', '/api/news/1'):
            response = self.client.get(path)
            item = response.json()['items'][0] if path == '/api/news' else response.json()
            self.assertEqual(item['summary'], '')
            self.assertEqual(response.headers['cache-control'], 'no-store')
        with news.connect() as conn:
            self.assertEqual(conn.execute('SELECT summary FROM articles').fetchone()[0], 'Real summary')

    def test_atomic_publish_idempotence_withdraw_all_endpoints_and_republish(self):
        first = reading.publish(edition())
        self.assertTrue(first['changed'])
        self.assertFalse(reading.publish(edition())['changed'])
        visible = self.content()
        self.assertEqual(visible['read_scope'], 'full_text')
        self.assertEqual(visible['blocks'][0]['block_id'], 'b001')
        self.assertNotIn('permissions', visible)
        self.assertNotIn('reviewer', json.dumps(visible))
        reading.withdraw(1, 'tester', 'revoked')
        revoked = self.content()
        self.assertEqual(revoked['read_scope'], 'unavailable')
        self.assertEqual(revoked['blocks'], [])
        self.assertNotEqual(visible['content_version'], revoked['content_version'])
        self.assertEqual(self.client.get('/api/news/1').json()['read_scope'], 'unavailable')
        self.assertEqual(self.client.get('/api/news').json()['items'][0]['summary'], '')
        with self.assertRaises(ValueError):
            reading.publish(edition())
        reading.publish(edition(), republish=True)
        self.assertNotEqual(self.content()['content_version'], visible['content_version'])
        self.assertEqual(self.content()['blocks'], visible['blocks'])

    def test_pending_denied_and_expired_permissions_fail_closed(self):
        for status in ('pending', 'denied', 'withdrawn', 'explicit_grant'):
            document = edition()
            document['permissions']['text']['status'] = status
            document['permissions']['text']['expires_at'] = '2025-01-01T00:00:00+00:00'
            reading.publish(document)
            self.assertEqual(self.content()['blocks'], [])
            self.assertEqual(self.content()['availability'], 'expired' if status == 'explicit_grant' else status)

    def test_deployment_import_cannot_replace_newer_or_withdrawn_edition(self):
        newer = edition(); newer['blocks'][0]['text'] = 'Newer reviewed content'
        reading.publish(newer)
        result = reading.publish(edition(), only_if_missing=True)
        self.assertEqual(result['status'], 'existing_edition_preserved')
        self.assertEqual(self.content()['blocks'][0]['text'], 'Newer reviewed content')
        reading.withdraw(1, 'tester', 'no permission')
        self.assertFalse(reading.publish(edition(), only_if_missing=True)['changed'])
        self.assertEqual(self.content()['read_scope'], 'unavailable')

    def test_legacy_guide_is_private_and_collection_does_not_change_policy(self):
        document = edition(mode='guide')
        reading.publish(document)
        news.store_records(news.parse_feed('nasa', rss(title='New metadata'))[0])
        item = self.client.get('/api/news/1').json()
        self.assertEqual(item['summary'], '')
        self.assertEqual(item['summary_kind'], 'none')
        self.assertEqual(self.content()['read_scope'], 'link_only')

    def test_migration_backup_identities_and_editions_survive_initialize(self):
        with news.connect() as conn:
            identities = [tuple(row) for row in conn.execute('SELECT id,canonical_url,first_seen_at FROM articles')]
            conn.execute('DROP TABLE reading_audit'); conn.execute('DROP TABLE reading_heads'); conn.execute('DROP TABLE article_contents')
            conn.execute('PRAGMA user_version=3')
        news.initialize()
        backup = news.DB_PATH.with_name(news.DB_PATH.name+'.before-v4.sqlite3')
        self.assertTrue(backup.exists())
        reading.publish(edition())
        news.initialize()
        self.assertEqual(self.content()['read_scope'], 'full_text')
        with news.connect() as conn:
            self.assertEqual([tuple(row) for row in conn.execute('SELECT id,canonical_url,first_seen_at FROM articles')], identities)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 5)
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute('SELECT id,canonical_url,first_seen_at FROM articles').fetchall(), identities)

    def test_rejects_unbounded_unknown_partial_and_ai_imports(self):
        mutations = [lambda d: d.update(mode='partial'), lambda d: d.update(completeness='unverified'),
                     lambda d: d['blocks'].append({'type': 'html', 'text': '<script>x</script>'}),
                     lambda d: d['blocks'].append({'type': 'paragraph', 'text': 'x'*12001}),
                     lambda d: d['blocks'].append({'type': 'table', 'rows': [['a'], ['b', 'c']]}),
                     lambda d: d['permissions']['ai_context'].update(d['permissions']['text']),
                     lambda d: d['permissions']['text'].update(expires_at='2027-01-01'),
                     lambda d: d.update(original_url='https://not-an-existing-article.invalid/')]
        for mutation in mutations:
            document = copy.deepcopy(edition()); mutation(document)
            with self.assertRaises(ValueError):
                reading.publish(document)
        self.assertEqual(self.content()['read_scope'], 'link_only')

    def test_public_has_no_mutation_or_arbitrary_fetch(self):
        self.assertEqual(self.client.get('/api/news/999/content').status_code, 404)
        self.assertEqual(self.client.get('/api/news/9999999999999999999999/content').status_code, 422)
        self.assertEqual(self.client.post('/api/news/1/content', json=edition()).status_code, 405)
        self.assertEqual(self.client.get('/api/news/https://example.com/content').status_code, 404)

    def test_consistent_backup_restore_preserves_content_and_rights_revision(self):
        reading.publish(edition())
        baseline = self.content()
        live = news.DB_PATH
        restored = live.with_name('restored.sqlite3')
        with closing(sqlite3.connect(live)) as origin, closing(sqlite3.connect(restored)) as target:
            origin.backup(target)
        reading.withdraw(1, 'tester', 'live changed after backup')
        self.assertEqual(self.content()['read_scope'], 'unavailable')
        try:
            news.DB_PATH = restored
            news.initialize()
            self.assertEqual(self.content(), baseline)
        finally:
            news.DB_PATH = live

    def test_other_sources_cannot_expose_even_approved_legacy_fulltext(self):
        for source in ('esa', 'cas_space', 'landspace', 'arianespace', 'ispace', 'gilmour'):
            domain = news.SOURCES[source]['domain']
            records = news.parse_feed(source, rss(domain=domain))[0]
            news.store_records(records)
            document = edition(url=records[0]['original_url'])
            result = reading.publish(document)
            article_id = result['article_id']
            for path in ('/api/news?source='+source, f'/api/news/{article_id}'):
                response = self.client.get(path)
                item = response.json()['items'][0] if '?' in path else response.json()
                self.assertEqual(item['summary'], '')
                self.assertEqual(item['reading_mode'], 'link_only')
            content = self.client.get(f'/api/news/{article_id}/content').json()
            self.assertEqual(content['blocks'], [])
            self.assertEqual(content['assets'], [])
            self.assertEqual(content['original_url'], records[0]['original_url'])
        self.assertEqual(reading_policy.source_policy('unreviewed_gov_domain'), 'link_only')

    def test_policy_change_invalidates_version_without_deleting_history(self):
        reading.publish(edition())
        previous = self.content()
        with patch.dict(reading_policy.SOURCE_READING_POLICY, {'nasa': 'link_only'}):
            current = self.content()
            self.assertEqual(current['reading_mode'], 'link_only')
            self.assertEqual(current['blocks'], [])
            self.assertNotEqual(current['content_version'], previous['content_version'])
            self.assertEqual(self.client.get('/api/news/1').json()['summary'], '')
        self.assertEqual(self.content(), previous)

    def test_government_candidate_requires_individual_text_grant(self):
        for source in ('cnsa', 'cmse'):
            records = news.parse_feed(source, rss(domain=news.SOURCES[source]['domain']))[0]
            news.store_records(records)
            with news.connect() as conn:
                article_id = conn.execute('SELECT id FROM articles WHERE canonical_url=?', (records[0]['canonical_url'],)).fetchone()[0]
            self.assertEqual(self.client.get(f'/api/news/{article_id}/content').json()['reading_mode'], 'link_only')
            reading.publish(edition(url=records[0]['original_url']))
            self.assertEqual(self.client.get(f'/api/news/{article_id}/content').json()['reading_mode'], 'full_text')
