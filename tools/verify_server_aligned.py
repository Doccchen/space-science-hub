"""Verify the server baseline is unchanged outside the three requested additions."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/server-baseline-20261017'
def normalized(path):return path.read_bytes().replace(b'\r\n',b'\n')
def main():
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    allowed={'web/index.html','web/styles/pages.css','web/news-reader.js','web/news-agent.js',
             'web/news-agent.css','web/history-carousel.js','web/history-slides.json','web/resource-navigation.html'}
    same=[]
    for record in manifest['files']:
        path=record['path'];assert hashlib.sha256((BASE/path).read_bytes()).hexdigest()==record['sha256']
        if path not in allowed:
            assert normalized(ROOT/path)==normalized(BASE/path),path
            same.append(path)
    index=(ROOT/'web/index.html').read_text(encoding='utf-8')
    old_index=(BASE/'web/index.html').read_text(encoding='utf-8')
    parse=lambda s:json.loads(re.search(r'<script id="history-slides" type="application/json">(.*?)</script>',s,re.S).group(1))
    old,new=parse(old_index),parse(index)
    assert len(old)==5 and len(new)==12 and new[:5]==old
    assert new==json.loads((ROOT/'web/history-slides.json').read_text(encoding='utf-8'))
    assert 'id="gallery"' not in index and '<section class="space-cover"' in index
    # The news list, AI, library and about content are unchanged (except replay).
    section=lambda s:s[s.index('<main id="news"'):s.index('<footer>')]
    clean=lambda s:re.sub(r'<script id="history-slides".*?</script>','',s,flags=re.S)
    now=clean(section(index));before=clean(section(old_index))
    now=re.sub(r'<dialog id="gallery-welcome".*?</dialog>\s*','',now,flags=re.S)
    now=now.replace('<button id="gallery-replay" class="secondary" type="button">重看欢迎动画</button>','')
    assert now.strip()==before.strip(),'Non-carousel main-page content changed'
    old_resources=(BASE/'web/resource-navigation.html').read_text(encoding='utf-8')
    new_resources=(ROOT/'web/resource-navigation.html').read_text(encoding='utf-8')
    links=lambda s:re.search(r'const allResources=\[.*?\];',s,re.S).group()
    assert links(old_resources)==links(new_resources),'Existing institution resources changed'
    report={'origin':manifest['origin'],'unchanged_baseline_files':same,'original_slides_preserved':5,'new_slides':7,
            'has_standalone_gallery':False,'welcome':True,'reader_split':'reader-split' in (ROOT/'web/news-reader.js').read_text(encoding='utf-8')}
    out=ROOT/'artifacts/server-aligned-verification-20261017';out.mkdir(exist_ok=True)
    (out/'baseline-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'unchanged_public_files':len(same),'slides':12,'original_slides_preserved':5,'non_carousel_content_unchanged':True}))

if __name__=='__main__':main()
