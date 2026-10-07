"""Optional, independently attributed NASA/ESA thumbnails in the private news volume."""
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from PIL import Image, ImageOps

from . import news, news_policy, news_image_store, news_assets
from .publisher_fetch import Publisher, checked_url

RIGHTS = {
    'nasa_guidelines':'https://www.nasa.gov/nasa-brand-center/images-and-media/',
    'esa_standard':'https://www.esa.int/About_Us/Law_at_ESA/Intellectual_Property_Rights/ESA_copyright_notice',
    'cc_by_sa_3_igo':'https://creativecommons.org/licenses/by-sa/3.0/igo/',
}

# Individually reviewed official creator affiliation; never allow arbitrary NASA/partner credits.
# NASA source: https://www.nasa.gov/people/jessica-u-meir/
NASA_REVIEWED_CREDITS = {'nasa', 'nasa/jessica meir'}

# Individually checked NASA releases, not a general NASA/* contributor wildcard.
# Source and supporting attribution evidence: docs/deployment/NASA历史配图署名修复-20261007.md
NASA_REVIEWED_ARTICLE_CREDITS = {
    '/news-release/la-nasa-abre-solicitudes-para-proxima-promocion-de-directores-de-vuelo':'nasa/robert markowitz',
    '/image-article/nasas-davinci-probe-can-stand-the-heat':'nasa/mike guinto',
    '/news-release/nasa-astronaut-christina-koch-to-join-nfl-fans-in-philadelphia':'nasa/john kraus',
    '/image-article/nasa-testing-aims-at-supercooled-large-droplet-aviation-safety':'nasa/quentin schwinn',
    '/image-article/nasa-astronaut-christina-koch-at-eagles-vs-rams':'nasa/thalia patrinos',
    '/news-release/nasa-to-stream-spacex-crew-12-return-splashdown-live':'nasa/anil menon',
}
_CREDIT_LABEL=r'(?:image\s+credits?|credits?|cr[eé]ditos?|photo)'


def reviewed_nasa_credit(url, credit):
    if credit.casefold() in NASA_REVIEWED_CREDITS:
        return True
    parsed=urlsplit(url)
    return (parsed.scheme=='https' and parsed.hostname=='www.nasa.gov'
            and NASA_REVIEWED_ARTICLE_CREDITS.get(parsed.path.rstrip('/'))==credit.casefold())


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS news_thumbnails(article_id INTEGER PRIMARY KEY REFERENCES articles(id),
      source_record_hash TEXT NOT NULL, source_url TEXT, object_key TEXT, mime TEXT, width INTEGER, height INTEGER,
      credit TEXT, rights_kind TEXT, state TEXT NOT NULL, attempts INTEGER NOT NULL, attempted_at REAL NOT NULL,
      version TEXT, error TEXT)''')


def eligible(item):
    return item['source_id'] in ('nasa','esa') and not news_policy.excluded_item(item)


def public_thumbnail(db, item):
    if not eligible(item):
        return None
    row=db.execute("SELECT * FROM news_thumbnails WHERE article_id=? AND state='ready' AND source_record_hash=?",
                   (item['id'],item['content_hash'])).fetchone()
    if not row or row['rights_kind'] not in RIGHTS:
        return None
    return {'url':f"/api/news/{item['id']}/thumbnail?v={row['version']}", 'credit':row['credit'],
            'rights_url':RIGHTS[row['rights_kind']], 'rights_kind':row['rights_kind'], 'source_page':item['original_url'],
            'changes':'等比例缩小并转换为 JPEG，保留画面范围。',
            'width':row['width'], 'height':row['height'], 'version':row['version']}


def parse_candidates(source, url, raw):
    """Credit must be attached to the actual figure; metadata alone is not permission."""
    tree=BeautifulSoup(raw,'html.parser');found=[]
    for image in tree.select('figure img, .hds-media img'):
        figure=image.find_parent(class_='hds-media') or image.find_parent('figure')
        if figure is None:
            continue
        credit_node=figure.select_one('.hds-credits, .credits, .credit, [data-credit]')
        if credit_node is None:
            caption_node=figure.find('figcaption')
            caption_credit=re.search(_CREDIT_LABEL+r'\s*:\s*(?:NASA(?:/[^:;\n]{1,100})?|ESA)\s*$',
                                     caption_node.get_text(' ',strip=True),re.I) if caption_node else None
            if caption_credit:
                credit=caption_credit.group(0).strip()
            else:
                continue
        else:
            credit=credit_node.get_text(' ',strip=True).strip()
        if not credit or len(credit)>300:
            continue
        caption=figure.get_text(' ',strip=True)+' '+str(image.get('alt',''))
        if '©' in caption.replace(credit,'',1):
            continue
        if re.search(r'courtesy|all rights reserved|getty|shutterstock|\bcopyright\b|\blogo\b|\binsignia\b|\blogotype\b',caption,re.I):
            continue
        rights_kind=None
        canonical_credit=re.sub(r'^'+_CREDIT_LABEL+r'\s*:\s*','',credit,flags=re.I).strip()
        canonical_credit=canonical_credit.removeprefix('©').strip()
        licenses={a.get('href','').rstrip('/') for a in figure.select('a[href]') if 'creativecommons.org/licenses/' in a.get('href','')}
        if source=='nasa' and reviewed_nasa_credit(url,canonical_credit):
            if licenses:
                continue
            rights_kind='nasa_guidelines'
        elif source=='esa' and canonical_credit.casefold()=='esa':
            if licenses and licenses!={RIGHTS['cc_by_sa_3_igo'].rstrip('/')}:
                continue
            if re.search(r'CC\s*BY',caption,re.I) and not licenses:
                continue
            rights_kind='cc_by_sa_3_igo' if licenses else 'esa_standard'
        if rights_kind:
            image_url=urljoin(url,image.get('src') or image.get('data-src') or '')
            try:
                parsed=checked_url(source,image_url,image=True)
                if parsed.hostname=='images-assets.nasa.gov':
                    image_url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
            except ValueError: continue
            found.append({'source_url':image_url,'credit':credit,'rights_kind':rights_kind})
    return found[:5]


def store_picture(item, candidate, client=None):
    if not eligible(item) or candidate['rights_kind'] not in RIGHTS:
        raise ValueError('Unsupported thumbnail scope or rights')
    checked_url(item['source_id'],candidate['source_url'],image=True)
    if not isinstance(candidate['credit'],str) or not 1<=len(candidate['credit'])<=300:
        raise ValueError('Image credit required')
    if (item['source_id']=='nasa' and candidate['rights_kind']!='nasa_guidelines'
            or item['source_id']=='esa' and candidate['rights_kind']=='nasa_guidelines'):
        raise ValueError('Image rights do not match publisher')
    client=client or Publisher(item['source_id'])
    raw,mime=client.get(candidate['source_url'],image=True,limit=8*1024*1024)
    news_assets.inspect_image(raw,mime)
    with Image.open(io.BytesIO(raw)) as image:
        thumb=ImageOps.exif_transpose(image)
        thumb.thumbnail((640,480))  # Preserve framing and any embedded attribution, never crop.
        if thumb.mode!='RGB':
            rgba=thumb.convert('RGBA');background=Image.new('RGB',rgba.size,'white');background.paste(rgba,mask=rgba.getchannel('A'));thumb=background
        buffer=io.BytesIO();thumb.save(buffer,format='JPEG',quality=85,optimize=True)
        data=buffer.getvalue();width,height=thumb.size
    digest=hashlib.sha256(data).hexdigest();key=f"{item['id']}/{uuid.uuid4().hex}/{digest}.jpg"
    news_image_store.write(key,data)
    with news.connect() as db:
        current=db.execute('SELECT * FROM articles WHERE id=?',(item['id'],)).fetchone()
        if not current or not eligible(dict(current)) or current['content_hash']!=item['content_hash']:
            raise ValueError('Article changed during thumbnail capture')
        db.execute('''INSERT INTO news_thumbnails(article_id,source_record_hash,source_url,object_key,mime,width,height,
          credit,rights_kind,state,attempts,attempted_at,version,error) VALUES(?,?,?,?,?,?,?,?,?,'ready',1,?,?,NULL)
          ON CONFLICT(article_id) DO UPDATE SET source_record_hash=excluded.source_record_hash,source_url=excluded.source_url,
          object_key=excluded.object_key,mime=excluded.mime,width=excluded.width,height=excluded.height,credit=excluded.credit,
          rights_kind=excluded.rights_kind,state='ready',attempts=1,attempted_at=excluded.attempted_at,version=excluded.version,error=NULL''',
          (item['id'],item['content_hash'],candidate['source_url'],key,'image/jpeg',width,height,candidate['credit'],
           candidate['rights_kind'],time.time(),digest[:24]))
    return {'article_id':item['id'],'state':'ready','credit':candidate['credit']}


def error_code(error):
    message=str(error)
    known={'Unreviewed NASA path':'article_or_image_path_not_allowed','Unreviewed ESA path':'article_or_image_path_not_allowed',
           'Unreviewed NASA image library path':'image_library_path_not_allowed',
           'Unreviewed publisher path':'url_path_not_allowed','Unreviewed publisher host':'host_not_allowed',
           'Publisher resolved to non-public address':'non_public_dns_address',
           'robots.txt disallows this material':'robots_disallowed','robots.txt returned HTML; review required':'robots_unconfirmed',
           'Article HTML unavailable':'article_not_html','Image type does not match response':'image_type_mismatch',
           'Unsupported or oversized image':'image_format_or_size','Article changed during thumbnail capture':'article_changed'}
    if message in known:
        return known[message]
    status=re.fullmatch(r'Publisher HTTP (\d{3}); no bypass attempted',message)
    if status:
        return 'upstream_http_'+status.group(1)
    if isinstance(error,OSError):
        return 'network_or_file_error'
    return 'capture_unavailable'


def diagnose(item):
    if not eligible(item):return {'article_id':item['id'],'state':'excluded'}
    try:
        raw,mime=Publisher(item['source_id']).get(item['original_url'])
        if mime not in ('text/html','application/xhtml+xml'):raise ValueError('Article HTML unavailable')
        tree=BeautifulSoup(raw,'html.parser')
        credits=[node.get_text(' ',strip=True)[:150] for node in tree.select('.hds-credits,.credits,.credit')][:5]
        return {'article_id':item['id'],'state':'inspected','image_nodes':len(tree.select('figure img,.hds-media img')),
                'credits':credits,'confirmed_candidates':len(parse_candidates(item['source_id'],item['original_url'],raw))}
    except (ValueError,OSError) as error:
        return {'article_id':item['id'],'state':'failed','error':error_code(error)}


def capture(item):
    if not eligible(item):
        return {'article_id':item['id'],'state':'excluded'}
    client=Publisher(item['source_id'])
    try:
        raw,mime=client.get(item['original_url'])
        if mime not in ('text/html','application/xhtml+xml'):
            raise ValueError('Article HTML unavailable')
        candidates=parse_candidates(item['source_id'],item['original_url'],raw)
        if candidates:
            return store_picture(item,candidates[0],client)
        state,error='unconfirmed','image_credit_or_usage_not_confirmed'
    except (ValueError,OSError) as issue:
        state,error='failed',error_code(issue)
    with news.connect() as db:
        db.execute('''INSERT INTO news_thumbnails(article_id,source_record_hash,state,attempts,attempted_at,error)
          VALUES(?,?,?,1,?,?) ON CONFLICT(article_id) DO UPDATE SET
          attempts=CASE WHEN source_record_hash=excluded.source_record_hash THEN attempts+1 ELSE 1 END,
          source_record_hash=excluded.source_record_hash,state=excluded.state,attempted_at=excluded.attempted_at,error=excluded.error''',
          (item['id'],item['content_hash'],state,time.time(),error))
    return {'article_id':item['id'],'state':state,'error':error}


def run_batch(limit=3):
    if type(limit) is not int or not 1<=limit<=10:
        raise ValueError('Thumbnail batch limit must be 1-10')
    with news.connect() as db:
        rows=db.execute('''SELECT a.* FROM articles a JOIN sources s ON s.id=a.source_id
          LEFT JOIN news_thumbnails t ON t.article_id=a.id
          WHERE a.source_id IN ('nasa','esa') AND s.enabled=1 AND news_is_excluded(a.source_id,a.title,a.original_url)=0
          AND (t.article_id IS NULL OR (t.state!='withdrawn' AND (t.source_record_hash!=a.content_hash OR
            (t.state!='ready' AND t.attempts<3 AND t.attempted_at<?))))
          ORDER BY a.published_at DESC,a.id DESC LIMIT ?''',(time.time()-6*3600,limit)).fetchall()
    return [capture(dict(row)) for row in rows]


async def loop():
    while True:
        try: await asyncio.to_thread(run_batch)
        except Exception: logging.warning('News thumbnail batch unavailable; keeping text entries')
        await asyncio.sleep(60)
