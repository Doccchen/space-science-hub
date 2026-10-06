import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import news, reading, auto_fulltext, review_worker, review_capture, review_store
from test_news import rss
from test_reading import edition


class AutoFulltextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = news.DB_PATH
        news.DB_PATH = Path(self.temp.name)/'news.sqlite3'
        news.initialize()
        news.store_records(news.parse_feed('nasa', rss())[0])
        self.env = patch.dict(os.environ, {'GOVERNMENT_FULLTEXT_AUTO': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop(); news.DB_PATH = self.old_db; self.temp.cleanup()

    def content(self):
        with news.connect() as conn:
            item = dict(conn.execute('SELECT * FROM articles WHERE id=1').fetchone())
            return reading.public_content(item, reading.editions(conn, [1]).get(1))

    def test_capture_auto_publishes_without_fabricated_license_or_admin_login(self):
        self.assertEqual(auto_fulltext.seed(), 1)
        document = edition(); document['permissions']['text'] = {'status': 'pending'}
        with patch.object(review_capture, 'capture', return_value=(document, [])):
            review_worker.run_one(('auto_text',))
        self.assertEqual(self.content()['reading_mode'], 'full_text')
        self.assertEqual(self.content()['usage']['status'], 'operator_direct')
        with news.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_user').fetchone()[0], 0)
            row = reading.editions(conn, [1])[1]
            self.assertEqual(json.loads(row['document'])['permissions']['text']['status'], 'pending')
            draft = conn.execute('SELECT document FROM review_drafts WHERE article_id=1').fetchone()['document']
            import hashlib
            self.assertEqual(hashlib.sha256(reading.validate(json.loads(draft)).encode()).hexdigest()[:24], row['version'])
        self.assertEqual(auto_fulltext.seed(), 0)
        with patch.dict(os.environ, {'GOVERNMENT_FULLTEXT_AUTO': '0'}):
            self.assertEqual(self.content()['reading_mode'], 'link_only')

    def test_withdrawal_and_old_full_text_are_never_overwritten(self):
        reading.publish(edition())
        self.assertEqual(auto_fulltext.seed(), 0)
        reading.withdraw(1, 'owner', 'takedown')
        self.assertEqual(auto_fulltext.seed(), 0)
        self.assertEqual(self.content()['reading_mode'], 'unavailable')

    def test_failures_cool_down_and_leave_history_intact(self):
        self.assertEqual(auto_fulltext.seed(), 1)
        with patch.object(review_capture, 'capture', side_effect=ValueError('Publisher temporarily failed')):
            review_worker.run_one(('auto_text',))
        self.assertEqual(auto_fulltext.seed(), 0)
        with news.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT state FROM review_jobs").fetchone()[0], 'failed')

    def test_companies_and_private_pending_drafts_do_not_become_public(self):
        news.store_records(news.parse_feed('esa', rss(domain='esa.int'))[0])
        pending = edition(); pending['permissions']['text'] = {'status': 'pending'}
        reading.publish(pending)
        self.assertEqual(self.content()['reading_mode'], 'link_only')
        self.assertEqual(auto_fulltext.seed(), 1)
        self.assertEqual(self.content()['reading_mode'], 'link_only')
        with news.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM review_jobs WHERE article_id=2').fetchone()[0], 0)

    def test_incremental_metadata_change_refreshes_text_and_preserves_identity(self):
        auto_fulltext.seed()
        document = edition()
        with patch.object(review_capture, 'capture', return_value=(document, [])):
            review_worker.run_one(('auto_text',))
        first = self.content()
        news.store_records(news.parse_feed('nasa', rss(title='Updated publisher title'))[0])
        self.assertEqual(auto_fulltext.seed(), 1)
        newer = edition(); newer['blocks'][0]['text'] = 'Updated full text'
        with patch.object(review_capture, 'capture', return_value=(newer, [])):
            review_worker.run_one(('auto_text',))
        self.assertEqual(self.content()['blocks'][0]['text'], 'Updated full text')
        self.assertNotEqual(first['content_version'], self.content()['content_version'])
        with news.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0], 1)

    def test_strict_parser_rejects_missing_text_and_special_structures(self):
        url = 'https://www.nasa.gov/news-release/test/'
        for html in ('<article><div class="entry-content"><p>Included</p>Unparsed text</div></article>',
                     '<article><div class="entry-content"><p>Included</p><math>Essential math</math></div></article>'):
            with self.assertRaises(ValueError):
                review_capture.parse('nasa', url, html.encode(), 'auto', strict=True)
        raw = (Path(__file__).parent/'fixtures/nasa-review-davinci.html').read_bytes()
        document, _ = review_capture.parse('nasa', url, raw, 'auto', strict=True)
        self.assertEqual(len(document['blocks']), 5)

    def test_automatic_queue_reserves_manual_image_slots(self):
        with news.connect() as conn:
            for _ in range(15):
                review_worker.enqueue(conn, 1, 'auto_text', {})
            with self.assertRaises(ValueError):
                review_worker.enqueue(conn, 1, 'auto_text', {})
            review_worker.enqueue(conn, 1, 'image', {})

    def test_original_language_and_author_metadata_are_preserved(self):
        html = '<html lang="es"><head><meta name="parsely-author" content="NASA editor"></head><body><article><div class="entry-content"><p>Texto original.</p></div></article></body></html>'
        document, _ = review_capture.parse('nasa', 'https://www.nasa.gov/news-release/test/', html.encode(), 'auto', strict=True)
        self.assertEqual(document['language'], 'es')
        self.assertIn('NASA editor', document['credit'])
        missing_language, _ = review_capture.parse('nasa', 'https://www.nasa.gov/news-release/test/', html.replace(' lang="es"', '').encode(), 'auto', strict=True)
        self.assertEqual(missing_language['language'], 'und')

    def test_old_private_draft_is_archived_but_never_used_as_automatic_text(self):
        private = edition(); private['blocks'][0]['text'] = 'Private editor annotation'
        private['permissions']['text'] = {'status': 'pending'}
        review_store.save_draft(1, private, 0, 'editor')
        auto_fulltext.seed()
        fresh = edition(); fresh['blocks'][0]['text'] = 'Fresh publisher text'
        with patch.object(review_capture, 'capture', return_value=(fresh, [])):
            review_worker.run_one(('auto_text',))
        self.assertEqual(self.content()['blocks'][0]['text'], 'Fresh publisher text')
        with news.connect() as conn:
            self.assertTrue(any('Private editor annotation' in row[0] for row in conn.execute('SELECT document FROM article_contents')))


if __name__ == '__main__':
    unittest.main()
