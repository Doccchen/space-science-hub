"""APOD exclusions apply before storage, pagination, public access and text fetches."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import news, news_policy, auto_fulltext, review_capture, review_worker
from backend.app import app
from test_news import rss


class ApodPolicy(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=news.DB_PATH
        news.DB_PATH=Path(self.temp.name)/'news.sqlite3';news.initialize()
        self.env=patch.dict(os.environ,{'COLLECT_ENABLED':'0','GOVERNMENT_FULLTEXT_AUTO':'0','AI_ENABLED':'0'})
        self.env.start()

    def tearDown(self):
        self.env.stop();news.DB_PATH=self.old;self.temp.cleanup()

    def legacy(self, title='APOD: 2026 October 7', url='https://science.nasa.gov/image-article/apod-2026-october-7/'):
        # Simulate data already stored by the older collector, without bypassing policy in production.
        with news.connect() as db:
            return db.execute('''INSERT INTO articles(source_id,canonical_url,original_url,title,summary,date_status,first_seen_at,last_seen_at,content_hash)
              VALUES('nasa',?,?,?,'','missing',?,?,'legacy-apod')''',(url,url,title,news.now(),news.now())).lastrowid

    def test_title_and_url_forms_without_broad_nasa_or_esa_exclusion(self):
        for title,url in [('APOD: Picture','https://www.nasa.gov/image-article/picture/'),
                          ('ＡＰＯＤ：Picture','https://www.nasa.gov/article/'),
                          ('Astronomy Picture of the Day: Stars','https://www.nasa.gov/article/'),
                          ('Stars','https://apod.nasa.gov/apod/ap261007.html'),
                          ('Stars','https://science.nasa.gov/apod/stars/'),
                          ('Stars','https://science.nasa.gov/image-article/apod-2026-october-7/')]:
            self.assertTrue(news_policy.excluded('nasa',title,url),(title,url))
        for title,url in [('NASA announces a mission','https://www.nasa.gov/news-release/mission/'),
                          ('Webb nebula image','https://science.nasa.gov/missions/webb/nebula/'),
                          ('New resources for APOD readers','https://www.nasa.gov/news-release/resources/'),
                          ('APODCAST project','https://www.nasa.gov/news-release/project/')]:
            self.assertFalse(news_policy.excluded('nasa',title,url),(title,url))
        self.assertFalse(news_policy.excluded('esa','APOD: unrelated title','https://www.esa.int/Newsroom'))

    def test_feed_skips_apod_before_store_and_apod_only_is_not_a_source_failure(self):
        records,rejected=news.parse_feed('nasa',rss(title='APOD: Stars'))
        self.assertEqual((records,rejected),([],1))
        ordinary=news.parse_feed('nasa',rss(title='Normal news'))[0]
        news.store_records([{**ordinary[0],'title':'APOD: Manual import'},ordinary[0]])
        self.assertEqual(news.list_articles()['items'][0]['title'],'Normal news')
        with news.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM articles').fetchone()[0],1)

    def test_old_rows_hidden_from_counts_pages_and_cursor_without_deletion(self):
        old=self.legacy()
        for number in range(3):news.store_records(news.parse_feed('nasa',rss(query='id='+str(number)))[0])
        first=news.list_articles(page=1,page_size=2);second=news.list_articles(page=2,page_size=2,snapshot=first['snapshot'])
        self.assertEqual((first['total'],first['total_pages'],len(second['items'])),(3,2,1))
        self.assertNotIn(old,[row['id'] for row in first['items']+second['items']])
        cursor=news.list_articles(limit=2)
        rest=news.list_articles(limit=2,cursor=cursor['next_cursor'])
        self.assertEqual(len(cursor['items'])+len(rest['items']),3)
        self.assertEqual(news.list_articles(source='nasa',page=1,page_size=2)['total'],3)
        with news.connect() as db:self.assertIsNotNone(db.execute('SELECT id FROM articles WHERE id=?',(old,)).fetchone())

    def test_hidden_details_content_and_images_return_404(self):
        old=self.legacy()
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/news?page=1&page_size=10').json()['total'],0)
            for suffix in ('','/content','/assets/example'):
                self.assertEqual(client.get('/api/news/'+str(old)+suffix).status_code,404)
            self.assertEqual(client.get('/api/health').status_code,200)

    def test_queued_old_apod_job_finishes_without_fetching_text(self):
        old=self.legacy()
        with news.connect() as db:
            job=review_worker.enqueue(db,old,'auto_text',{'actor':'government-auto','revision':0,'source_record_hash':'legacy-apod'})
        with patch.dict(os.environ,{'GOVERNMENT_FULLTEXT_AUTO':'1'}),patch.object(review_capture,'capture',side_effect=AssertionError('APOD must not fetch')):
            self.assertEqual(auto_fulltext.seed(),0)
            self.assertTrue(review_worker.run_one(('auto_text',)))
        with news.connect() as db:
            row=db.execute('SELECT state,result FROM review_jobs WHERE id=?',(job,)).fetchone()
            self.assertEqual(row['state'],'done')
            self.assertEqual(json.loads(row['result'])['reason'],'excluded_apod')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reading_heads').fetchone()[0],0)


if __name__=='__main__':unittest.main()
