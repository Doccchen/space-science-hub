"""Read-only snapshot of explicitly public frontend files, never server config."""
import concurrent.futures
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'artifacts/server-baseline-20261017'
ORIGIN='https://8.137.164.100:8080'
NAMES=['style.css','resources.css','glass-theme.css','ai.css','frontend-refinement.css','quiet-ui.css',
       'editorial.css','ai-layout.css','site-motion.css','design-system.css',
       'news-agent.css','news-agent.js','gallery-welcome.js','resource-navigation.html','history-slides.json']

def fetch(name):
    url=ORIGIN+('/' if name=='index.html' else '/assets/'+name)
    with urllib.request.urlopen(url,timeout=30) as response:
        assert response.geturl().startswith(ORIGIN+'/')
        data=response.read()
    path=DEST/'web'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return {'path':'web/'+name,'url':url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

def main():
    records=[fetch('index.html')]
    index=(DEST/'web/index.html').read_text(encoding='utf-8')
    names=set(NAMES)-{'gallery-welcome.js'}
    names.update(urlsplit(url).path.removeprefix('/assets/') for url in re.findall(r'/(?:assets)/[^"\s<>]+',index))
    assert all('..' not in Path(n).parts and not Path(n).is_absolute() for n in names)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records.extend(pool.map(fetch,sorted(names)))
    manifest={'origin':ORIGIN,'captured_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'files':records}
    (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(records),'destination':str(DEST),'index_sha256':records[0]['sha256']}))

if __name__=='__main__':main()
