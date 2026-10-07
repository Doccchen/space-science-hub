"""Historical backfill stays scoped, respects withdrawal, and attempts each snapshot item once."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import news
from tools import backfill_nasa_fulltext_images as backfill


class NasaBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=news.DB_PATH
        news.DB_PATH=Path(self.temp.name)/'news.sqlite3';news.initialize()
        with news.connect() as db:
            for identity in range(1,8):
                source='esa' if identity==7 else 'nasa'
                title='Astronomy Picture of the Day' if identity==6 else 'News '+str(identity)
                db.execute("""INSERT INTO articles(id,source_id,canonical_url,original_url,title,summary,date_status,
                    first_seen_at,last_seen_at,content_hash) VALUES(?,?,?,?,?,'','missing','2020','2020',?)""",
                    (identity,source,'https://example.org/'+str(identity),'https://example.org/'+str(identity),title,'hash'+str(identity)))
            for identity,state,attempts in [(1,'ready',1),(2,'failed',3),(3,'unconfirmed',3),(4,'withdrawn',3)]:
                db.execute('INSERT INTO news_thumbnails(article_id,source_record_hash,state,attempts,attempted_at) VALUES(?,?,?,?,?)',
                    (identity,'hash'+str(identity),state,attempts,0))
        def public(db,rows):
            return [{**dict(row),'reading_mode':'link_only' if row['id']==5 else 'full_text',
                     'thumbnail':{'credit':'NASA'} if row['id']==1 else None} for row in rows]
        self.reader=patch('backend.reading.public_rows',side_effect=public);self.reader.start()

    def tearDown(self):
        self.reader.stop();news.DB_PATH=self.old;self.temp.cleanup()

    def test_inventory_is_dry_and_only_missing_public_nasa_full_text(self):
        with patch('backend.news_thumbnails.capture') as capture:
            result=backfill.run()
        capture.assert_not_called()
        self.assertEqual(result['selected_ids'],[2,3])
        self.assertEqual(result['nasa_full_text'],4)
        self.assertEqual(result['withdrawn_skipped'],1)

    def test_explicit_backfill_retries_old_failures_once_and_respects_bound(self):
        with patch('backend.news_thumbnails.capture',side_effect=lambda row:{'article_id':row['id'],'state':'unconfirmed'}) as capture:
            report=backfill.run(100,True)
        self.assertEqual([call.args[0]['id'] for call in capture.call_args_list],[2,3])
        self.assertEqual(report['outcomes'],{'unconfirmed':2})
        with patch('backend.news_thumbnails.capture',return_value={'article_id':2,'state':'ready'}) as capture:
            report=backfill.run(1,True)
        self.assertEqual(capture.call_count,1);self.assertEqual(report['deferred'],1)

    def test_concurrent_withdrawal_after_inventory_is_not_overwritten(self):
        original=backfill.inventory
        def snapshot():
            result=original()
            with news.connect() as db:db.execute("UPDATE news_thumbnails SET state='withdrawn' WHERE article_id=2")
            return result
        with patch.object(backfill,'inventory',side_effect=snapshot),patch('backend.news_thumbnails.capture',return_value={'article_id':3,'state':'ready'}) as capture:
            report=backfill.run(100,True)
        self.assertEqual([call.args[0]['id'] for call in capture.call_args_list],[3])
        self.assertEqual(report['results'][0]['reason'],'withdrawn')


if __name__=='__main__':unittest.main()
