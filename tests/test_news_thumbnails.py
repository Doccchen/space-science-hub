"""Owned synthetic images only; no publisher traffic or inferred third-party permissions."""
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
from backend import news,news_thumbnails as thumbnails,news_image_store,reading
from backend.app import app
from backend.publisher_fetch import checked_url
from test_news import rss


class Thumbnails(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=news.DB_PATH;news.DB_PATH=Path(self.temp.name)/'news.sqlite3'
        news.initialize();self.env=patch.dict(os.environ,{'COLLECT_ENABLED':'0','AI_ENABLED':'0','NEWS_THUMBNAILS_ENABLED':'0'});self.env.start()
        news.store_records(news.parse_feed('nasa',rss())[0]);news.store_records(news.parse_feed('esa',rss(domain='esa.int'))[0])
        buffer=io.BytesIO();Image.new('RGB',(800,600),'navy').save(buffer,format='PNG');self.image=buffer.getvalue()

    def tearDown(self):
        self.env.stop();news.DB_PATH=self.old;self.temp.cleanup()

    def item(self,identity):
        with news.connect() as db:return dict(db.execute('SELECT * FROM articles WHERE id=?',(identity,)).fetchone())

    def candidate(self,source):
        return {'source_url':('https://www.nasa.gov/wp-content/uploads/test.png' if source=='nasa' else 'https://www.esa.int/var/esa/storage/images/test.png'),
                'credit':source.upper(),'rights_kind':'nasa_guidelines' if source=='nasa' else 'esa_standard'}

    def store(self,identity):
        item=self.item(identity)
        with patch('backend.news_thumbnails.Publisher') as publisher:
            publisher.return_value.get.return_value=(self.image,'image/png')
            return thumbnails.store_picture(item,self.candidate(item['source_id']))

    def test_figure_credit_is_required_and_og_image_alone_not_accepted(self):
        html=b'<meta property="og:image" content="https://www.nasa.gov/wp-content/uploads/test.png">'
        self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',html),[])
        owned=b'<figure><img src="/wp-content/uploads/test.png"><figcaption>Credit: NASA</figcaption></figure>'
        self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',owned)[0]['rights_kind'],'nasa_guidelines')
        for credit in ('NASA/SpaceX','Courtesy of NASA','NASA/Getty Images','NASA, all rights reserved'):
            raw=f'<figure><img src="/wp-content/uploads/test.png"><span class="hds-credits">{credit}</span></figure>'.encode()
            self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',raw),[])
        logo=b'<figure><img alt="NASA logo" src="/wp-content/uploads/logo.png"><span class="hds-credits">NASA</span><figcaption>NASA logo</figcaption></figure>'
        self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',logo),[])

    def test_reviewed_historical_credits_are_bound_to_the_specific_release(self):
        for path,credit in thumbnails.NASA_REVIEWED_ARTICLE_CREDITS.items():
            raw=f'<div class="hds-media"><figure><img src="/wp-content/uploads/test.png"></figure><figcaption><span class="hds-credits">Credit: {credit}</span></figcaption></div>'.encode()
            parsed=thumbnails.parse_candidates('nasa','https://www.nasa.gov'+path+'/',raw)
            self.assertEqual(len(parsed),1,path)
            self.assertEqual(parsed[0]['credit'],'Credit: '+credit)
            self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/unreviewed/',raw),[])
            self.assertEqual(thumbnails.parse_candidates('nasa','https://evil.test'+path+'/',raw),[])

    def test_spanish_caption_credit_is_separated_from_description(self):
        url='https://www.nasa.gov/news-release/la-nasa-abre-solicitudes-para-proxima-promocion-de-directores-de-vuelo/'
        raw='<div class="hds-media"><figure><img src="/wp-content/uploads/flight-directors.jpg"></figure><figcaption><div class="hds-caption-text">El equipo de control de vuelo. Crédito: NASA/Robert Markowitz</div></figcaption></div>'.encode()
        parsed=thumbnails.parse_candidates('nasa',url,raw)
        self.assertEqual(len(parsed),1)
        self.assertEqual(parsed[0]['credit'],'Crédito: NASA/Robert Markowitz')
        for replacement in ('NASA/Unknown Person','NASA/Getty Images','NASA, ESA, Leah Hustak (STScI)'):
            self.assertEqual(thumbnails.parse_candidates('nasa',url,raw.replace(b'NASA/Robert Markowitz',replacement.encode())),[])

    def test_esa_standard_and_explicit_figure_cc_licence_remain_distinct(self):
        root='<figure><img src="/var/esa/storage/images/test.png"><span class="credit">ESA</span>{}</figure>'
        for extra,expected in [('', 'esa_standard'),('<a href="https://creativecommons.org/licenses/by-sa/3.0/igo/">Licence</a>','cc_by_sa_3_igo')]:
            parsed=thumbnails.parse_candidates('esa','https://www.esa.int/ESA_Multimedia/Images/test',root.format(extra).encode())
            self.assertEqual(parsed[0]['rights_kind'],expected)
        restricted=root.format('<a href="https://creativecommons.org/licenses/by-nc/4.0/">Restricted</a>').encode()
        self.assertEqual(thumbnails.parse_candidates('esa','https://www.esa.int/ESA_Multimedia/Images/test',restricted),[])

    def test_stored_thumbnail_is_small_jpeg_with_credit_and_no_cropping(self):
        self.store(1)
        with news.connect() as db:
            row=db.execute('SELECT * FROM news_thumbnails WHERE article_id=1').fetchone()
            preview=thumbnails.public_thumbnail(db,self.item(1))
        self.assertEqual((row['width'],row['height'],row['mime']),(640,480,'image/jpeg'))
        self.assertEqual(preview['credit'],'NASA');self.assertEqual(preview['rights_url'],thumbnails.RIGHTS['nasa_guidelines'])
        self.assertIn('转换为 JPEG',preview['changes'])
        self.assertTrue(news_image_store.path(row['object_key']).is_file())

    def test_esa_image_does_not_enable_esa_full_text_and_endpoints_are_versioned(self):
        self.store(2)
        with TestClient(app) as client:
            detail=client.get('/api/news/2').json();self.assertEqual(detail['reading_mode'],'link_only')
            self.assertEqual(detail['summary'],'');self.assertEqual(detail['thumbnail']['credit'],'ESA')
            response=client.get(detail['thumbnail']['url']);self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['content-type'],'image/jpeg');self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/api/news/2/thumbnail?v=wrong').status_code,404)
            self.assertEqual(client.get('/api/news/1/thumbnail').status_code,404)

    def test_withdrawal_and_changed_article_hide_images_but_preserve_files(self):
        self.store(1)
        with news.connect() as db:
            row=db.execute('SELECT * FROM news_thumbnails WHERE article_id=1').fetchone();key=row['object_key']
            db.execute("UPDATE news_thumbnails SET state='withdrawn',attempts=3 WHERE article_id=1")
        news.store_records(news.parse_feed('nasa',rss(title='Updated title'))[0])
        with patch('backend.news_thumbnails.capture',side_effect=lambda item: {'article_id':item['id']}):
            self.assertNotIn(1,[result['article_id'] for result in thumbnails.run_batch()])
        with TestClient(app) as client:self.assertEqual(client.get('/api/news/1/thumbnail').status_code,404)
        self.assertTrue(news_image_store.path(key).is_file())

    def test_apod_and_other_publishers_are_never_requested(self):
        item={**self.item(1),'title':'APOD: Space'}
        with patch('backend.news_thumbnails.Publisher',side_effect=AssertionError('no APOD traffic')):
            self.assertEqual(thumbnails.capture(item)['state'],'excluded')
        self.assertFalse(thumbnails.eligible({**item,'source_id':'cnsa','title':'Ordinary'}))
        for url in ('https://evil.test/var/esa/storage/images/x.png','http://127.0.0.1/var/esa/storage/images/x.png','https://www.esa.int/var/esa/storage/images/../x.png'):
            with self.assertRaises(ValueError):checked_url('esa',url,image=True)

    def test_nasa_earth_observatory_article_scope(self):
        for name in ('arctic-sea-ice-shrinks-to-its-2026-minimum','october-2026-satellite-puzzler'):
            checked_url('nasa','https://science.nasa.gov/earth/earth-observatory/'+name+'/')

    def test_reviewed_nasa_creator_keeps_full_credit_without_partner_wildcard(self):
        template='<figure class="hds-media"><img src="/wp-content/uploads/2026/10/own.png"><figcaption><div class="hds-caption-text">Own NASA image</div><div class="hds-credits">Credit: {}</div></figcaption></figure>'
        candidate=thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',template.format('NASA/Jessica Meir').encode())
        self.assertEqual(candidate[0]['credit'],'Credit: NASA/Jessica Meir')
        for creator in ('NASA/Unknown Person','NASA/SpaceX','NASA/ESA'):
            self.assertEqual(thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',template.format(creator).encode()),[])

    def test_nasa_media_credit_is_a_sibling_of_inner_figure(self):
        raw=b'<div class="hds-media"><figure><img src="/wp-content/uploads/test.png"></figure><figcaption><div class="hds-credits">Credit: NASA/Jessica Meir</div></figcaption></div>'
        candidate=thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',raw)
        self.assertEqual(len(candidate),1)

    def test_official_nasa_image_library_cdn_from_actual_article(self):
        url='https://images-assets.nasa.gov/image/iss074e0458241/iss074e0458241~large.jpg?w=1920&h=1280&fit=clip'
        checked_url('nasa',url,image=True)
        raw=f'<div class="hds-media"><div class="hds-media-wrapper"><figure><img src="{url}"></figure><figcaption><div class="hds-credits">Credit: NASA/Jessica Meir</div></figcaption></div></div>'.encode()
        candidates=thumbnails.parse_candidates('nasa','https://www.nasa.gov/news-release/test/',raw)
        self.assertEqual(len(candidates),1)
        self.assertNotIn('?',candidates[0]['source_url'])
        with self.assertRaises(ValueError):checked_url('nasa',url,image=False)
        for invalid in ('https://images-assets.nasa.gov/private/test.jpg','https://images-assets.nasa.gov/image/../x.jpg',
                        'https://images-assets.nasa.gov.evil.test/image/id/x.jpg','http://images-assets.nasa.gov/image/id/x.jpg'):
            with self.assertRaises(ValueError):checked_url('nasa',invalid,image=True)

    def test_diagnostic_errors_are_specific_without_raw_exception_leaks(self):
        with patch('backend.news_thumbnails.Publisher') as publisher:
            publisher.return_value.get.side_effect=ValueError('robots.txt disallows this material')
            result=thumbnails.diagnose(self.item(1))
            self.assertEqual(result['error'],'robots_disallowed')
            result=thumbnails.capture(self.item(1))
            self.assertEqual(result['error'],'robots_disallowed')
        self.assertEqual(thumbnails.error_code(OSError('secret-looking network data')),'network_or_file_error')

    def test_missing_credit_and_network_failure_remain_text_only_and_cool_down(self):
        item=self.item(1)
        with patch('backend.news_thumbnails.Publisher') as publisher:
            publisher.return_value.get.return_value=(b'<figure><img src="/wp-content/uploads/test.png"></figure>','text/html')
            self.assertEqual(thumbnails.capture(item)['state'],'unconfirmed')
        with patch('backend.news_thumbnails.Publisher') as publisher:
            publisher.return_value.get.side_effect=OSError('private network details must not leak')
            self.assertEqual(thumbnails.capture(self.item(2))['state'],'failed')
        with patch('backend.news_thumbnails.capture',side_effect=AssertionError('cooldown')):
            self.assertEqual(thumbnails.run_batch(),[])
        with TestClient(app) as client:
            self.assertIsNone(client.get('/api/news/1').json()['thumbnail'])
            self.assertNotIn('private network details',client.get('/api/news').text)

    def test_snapshot_backup_includes_thumbnail_files(self):
        from tools import backup_review
        self.store(2);target=Path(self.temp.name)/'snapshot'
        manifest=backup_review.backup(news.DB_PATH,target)
        self.assertEqual(len(manifest['images']),1)
        self.assertTrue((target/'news-images'/manifest['images'][0]['key']).is_file())


if __name__=='__main__':unittest.main()
