"""Capture public news and existing attributed thumbnail bytes for an offline visual preview."""
import base64
import json
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent.parent
BASE='http://8.137.164.100:8080'


def main():
    with urlopen(BASE+'/api/news?page=1&page_size=20',timeout=20) as response:
        news=json.load(response)
    with urlopen(BASE+'/api/news/sources',timeout=20) as response:
        sources=json.load(response)
    pictures={}
    for item in news['items']:
        thumbnail=item.get('thumbnail')
        if not thumbnail or not thumbnail.get('credit'):continue
        url=thumbnail.get('url','')
        if not url.startswith('/api/news/'+str(item['id'])+'/thumbnail?v='):continue
        with urlopen(BASE+url,timeout=20) as response:
            data=response.read(2*1024*1024)
            if response.headers.get_content_type()!='image/jpeg' or not data.startswith(b'\xff\xd8'):
                raise ValueError('Unexpected thumbnail type')
        pictures[url]='data:image/jpeg;base64,'+base64.b64encode(data).decode('ascii')
    folder=ROOT/'artifacts/magazine-preview';folder.mkdir(parents=True,exist_ok=True)
    (folder/'public-news-snapshot.json').write_text(json.dumps({'articles':news['items'],'sources':sources['items'],'thumbnails':pictures},ensure_ascii=False),encoding='utf-8')
    print('Public preview snapshot:',len(news['items']),'stories;',len(pictures),'existing credited images. No server writes.')


if __name__=='__main__':main()
