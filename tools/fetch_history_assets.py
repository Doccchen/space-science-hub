"""Acquire only the four reviewed history assets; preserve source pages and file hashes."""
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
ITEMS = [
 ('history-mengtian.jpg','https://commons.wikimedia.org/wiki/File:Mengtian_launch.jpg','commons'),
 ('history-tianhe.png','https://commons.wikimedia.org/wiki/File:Tianhe_Core_Module_Rendering_no_background.png','commons'),
 ('history-apollo11.jpg','https://www.nasa.gov/image-article/apollo-11-lifts-off-3/','og'),
 ('history-rosetta.jpg','https://www.esa.int/ESA_Multimedia/Images/2014/08/Comet_on_3_August_2014_-_NavCam','og'),
]


def get(url):
    with urlopen(Request(url, headers={'User-Agent':'Xingzhihang/1.0 (educational asset attribution review)'}), timeout=25) as response:
        return response.read()


def main():
    evidence = ROOT / 'artifacts/history-image-sources'
    evidence.mkdir(parents=True, exist_ok=True)
    records = []
    for name, source, mode in ITEMS:
        page = get(source).decode('utf-8')
        (evidence / (name+'.source.html')).write_text(page, encoding='utf-8')
        if mode == 'commons':
            match = re.search(r'<div class="fullImageLink"[^>]*>\s*<a href="([^"]+)"', page)
        else:
            match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page)
        if not match:
            raise RuntimeError('Asset URL not found: '+source)
        image_url = urljoin(source, html.unescape(match[1]))
        if 'nasa.gov' in image_url:
            image_url = image_url.split('?')[0] + '?resize=1600,1250'
        data = get(image_url)
        if not (data.startswith(b'\xff\xd8') or data.startswith(b'\x89PNG')):
            raise RuntimeError('Unexpected image bytes: '+name)
        if len(data) >= 1500000:
            raise RuntimeError('Asset too large: '+name)
        (ROOT / 'web' / name).write_bytes(data)
        records.append({'file':name,'source_url':source,'download_url':image_url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        print(name, len(data), flush=True)
        (evidence/'downloads.json').write_text(json.dumps(records, ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
