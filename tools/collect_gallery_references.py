"""Collect unmodified official imagery and source evidence for the proposed gallery."""
import hashlib
import argparse
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlparse

import httpx
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/gallery-research-20261012'
CATALOG=[
 ('01-cosmic-cliffs','宇宙悬崖','深空','https://science.nasa.gov/asset/webb/cosmic-cliffs-in-the-carina-nebula-nircam-image/'),
 ('02-earthset','月球背面的地落','地球与月球','https://science.nasa.gov/earth/earth-observatory/earthset-from-the-lunar-far-side/'),
 ('03-saturn','土星背光全景','太阳系','https://science.nasa.gov/resource/the-day-the-earth-smiled/'),
 ('04-aurora','轨道上的极光','地球与空间站','https://www.nasa.gov/image-article/international-space-station-soars-above-an-aurora/'),
 ('05-artemis-launch','Artemis I 夜间发射','发射','https://www.nasa.gov/humans-in-space/view-the-best-images-from-nasas-artemis-i-mission/'),
 ('06-stephans-quintet','斯蒂芬五重星系','深空','https://science.nasa.gov/asset/webb/stephans-quintet-nircam-and-miri-composite-image/'),
 ('07-pillars','创生之柱','深空','https://science.nasa.gov/asset/webb/pillars-of-creation-nircam-image/'),
 ('08-jupiter','木星大红斑与风暴','太阳系','https://science.nasa.gov/photojournal/jupiter-marble/'),
 ('09-spacewalk','独自漂浮在地球上方','载人航天','https://www.nasa.gov/image-article/astronaut-bruce-mccandless-first-ever-untethered-spacewalk-3/'),
 ('10-sunrise','空间站轨道日出','地球与空间站','https://www.nasa.gov/image-article/good-morning-earth/'),
 ('11-comet','67P 彗星近景','太阳系','https://www.esa.int/ESA_Multimedia/Images/2015/02/Comet_on_22_January_2015_NavCam'),
 ('12-andromeda','仙女座星系全景','深空','https://science.nasa.gov/resource/hubbles-high-definition-panoramic-view-of-the-andromeda-galaxy/'),
 ('13-aurora-horizon','地球地平线上的极光','地球与空间站','https://www.nasa.gov/image-article/radiant-aurora-crowns-earths-horizon/'),
]


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__();self.og='';self.images=[];self.downloads=[];self.text=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta' and attrs.get('property')=='og:image':self.og=attrs.get('content','')
        if tag=='img' and attrs.get('src'):self.images.append({'url':attrs['src'],'alt':attrs.get('alt','')})
        for name,value in attrs.items():
            if value and ('download' in name or name=='href') and re.search(r'\.(?:jpg|jpeg|png|tif|tiff)(?:\?|$)',value,re.I):
                self.downloads.append(value)
    def handle_data(self,value):
        if value.strip():self.text.append(value.strip())


def collect(entry):
    identity,title,theme,source=entry
    target=OUT/identity;target.mkdir(parents=True,exist_ok=True)
    result={'id':identity,'title':title,'theme':theme,'source_url':source,'status':'pending'}
    try:
        with httpx.Client(follow_redirects=True,timeout=45) as client:
            page=client.get(source);page.raise_for_status()
            (target/'source.html').write_text(page.text,encoding='utf-8')
            meta=Metadata();meta.feed(page.text)
            (target/'source-text.txt').write_text('\n'.join(meta.text),encoding='utf-8')
            image_url=urljoin(str(page.url),meta.og or meta.images[0]['url'])
            downloads=list(dict.fromkeys(urljoin(str(page.url),v) for v in meta.downloads if 'favicon' not in v))
            original_links=[u for u in downloads if '/content/dam/' in u or 'esa/storage/images/' in u]
            if original_links:
                display=[u for u in original_links if '2000' in u.rsplit('/',1)[-1] and u.lower().endswith('.png')]
                jpeg=[u for u in original_links if u.lower().endswith(('.jpg','.jpeg'))]
                image_url=next(iter(display or jpeg),image_url)
            if identity=='05-artemis-launch':
                image_url=next(image['url'] for image in meta.images if 'artemis_i_launch_nhq' in image['url'])
            if identity in ('04-aurora','09-spacewalk'):
                nasa_id='iss067e090349' if identity=='04-aurora' else 's84-27232'
                asset=client.get('https://images-api.nasa.gov/asset/'+nasa_id)
                if asset.is_success:
                    urls=[value['href'] for value in asset.json().get('collection',{}).get('items',[])]
                    originals=[u for u in urls if u.lower().endswith('~orig.jpg')]
                    if originals:image_url=originals[0];original_links.extend(originals)
            result.update(image_url=image_url,original_image_links=original_links,download_links=downloads,image_candidates=meta.images)
            with client.stream('GET',image_url) as response:
                response.raise_for_status();data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>25000000:raise ValueError('Official image exceeds research download limit; URL retained')
            with Image.open(io.BytesIO(data)) as image:
                width,height=image.size;format=image.format.lower()
                if min(width,height)<400:raise ValueError('Image is too small for a gallery reference')
            extension='jpg' if format=='jpeg' else format
            path=target/('image.'+extension);path.write_bytes(data)
            result.update(status='downloaded',local_path=str(path),width=width,height=height,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    except Exception as error:
        result.update(status='needs_review',error=type(error).__name__+': '+str(error))
    (target/'metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('id','status','width','height','error') if key in result}),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only',nargs='*');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    entries=[entry for entry in CATALOG if not args.only or entry[0] in args.only]
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(collect,entries))
    if args.only and (OUT/'manifest.json').is_file():
        old=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
        by_id={item['id']:item for item in old+results};results=[by_id[key] for key in sorted(by_id)]
    (OUT/'manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'downloaded':sum(item['status']=='downloaded' for item in results),'total':len(results)}))


if __name__=='__main__':main()
