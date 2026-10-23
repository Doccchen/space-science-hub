"""Collect live baselines and package only the guide/Markdown update."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/guides-release-20261021'
WEB = ['web/index.html', 'web/news-reader.js', 'web/ai-ui.js', 'web/research.html', 'web/research.js',
       'web/article-renderer.js', 'web/article.css', 'web/guides.html', 'web/guides.js', 'web/styles/pages.css']
WEB += [str(p.relative_to(ROOT)).replace('\\', '/') for p in sorted((ROOT/'web/guides').glob('*')) if p.is_file()]
GROUPS = {'app': ['backend/reading.py'] + WEB, 'admin': ['backend/reading.py']}
SOURCE_ONLY = ['tools/build_styles.py']
CONTAINERS = {'app':'space-news-app-1','admin':'space-news-admin-1','reader':'space-news-paper-search'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    code = 'GROUPS=' + repr(GROUPS) + '\nCONTAINERS=' + repr(CONTAINERS) + '\n' + '''import hashlib,json,subprocess,base64
from pathlib import Path
result={'containers':{},'baselines':{},'config_hashes':{},'source_baselines':{}}
for role,names in GROUPS.items():
 d=json.loads(subprocess.check_output(['docker','inspect',CONTAINERS[role]]))[0]
 assert d['State']['Health']['Status']=='healthy'
 result['containers'][role]=d['Id']
 inner="import hashlib,json,base64;from pathlib import Path;print(json.dumps({n:base64.b64encode((Path('/app')/n).read_bytes()).decode() if (Path('/app')/n).is_file() else None for n in "+repr(names)+"}))"
 blobs=json.loads(subprocess.check_output(['docker','exec',d['Id'],'python','-c',inner]))
 result['baselines'][role]={n:hashlib.sha256(base64.b64decode(b)).hexdigest() if b else None for n,b in blobs.items()}
 result.setdefault('baseline_blobs',{})[role]=blobs
for name in ('compose.yaml','compose.paper-search.yaml','.env','.env.reader'):
 result['config_hashes'][name]=hashlib.sha256((Path('/opt/space-news')/name).read_bytes()).hexdigest()
for name in {n for names in GROUPS.values() for n in names}|{'tools/build_styles.py'}:
 p=Path('/opt/space-news')/name
 result['source_baselines'][name]=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
print(json.dumps(result))
'''
    response = subprocess.run(['ssh','-i',str(ROOT.parent/'GPT.pem'),'-o','BatchMode=yes','-o','ConnectTimeout=12',
                               'root@8.137.164.100','python3','-'], input=code.encode(), stdout=subprocess.PIPE, check=True)
    manifest = json.loads(response.stdout)
    import base64
    for role, blobs in manifest.pop('baseline_blobs').items():
        for name, blob in blobs.items():
            if blob is not None:
                target = OUT/'baseline'/role/name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(base64.b64decode(blob))
    names = sorted(set(SOURCE_ONLY + [n for group in GROUPS.values() for n in group]))
    manifest['groups'] = GROUPS
    manifest['files'] = {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    with tarfile.open(OUT/'release.tar.gz','w:gz') as archive:
        for name in names: archive.add(ROOT/name, arcname=name)
    manifest['archive_sha256'] = hashlib.sha256((OUT/'release.tar.gz').read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2))
    for name in ('deploy_guides.py','deploy_news_switch.py'):
        (OUT/name).write_bytes((ROOT/'tools'/name).read_bytes())
    print(json.dumps({'files':len(names),'groups':{s:len(n) for s,n in GROUPS.items()},'archive_sha256':manifest['archive_sha256']}))


if __name__ == '__main__': main()
