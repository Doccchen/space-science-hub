"""Capture live static baselines for a narrowly scoped research-workspace release."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/research-release-20261020'
GROUPS = {
    'app': ['web/index.html', 'web/news-reader.js', 'web/resource-navigation.html',
            'web/research.html', 'web/research.css', 'web/research.js'],
    'reader': ['reader_web/index.html'],
}
CONTAINERS = {'app': 'space-news-app-1', 'reader': 'space-news-paper-search'}


def main():
    code = '''import base64,hashlib,json,subprocess
from pathlib import Path
result={'containers':{},'baselines':{},'config_hashes':{},'files':{}}
for service,names in GROUPS.items():
 d=json.loads(subprocess.check_output(['docker','inspect',CONTAINERS[service]]))[0]
 assert d['State']['Health']['Status']=='healthy', service
 result['containers'][service]=d['Id']
 pcode="from pathlib import Path;import base64,json;print(json.dumps({n:base64.b64encode((Path('/app')/n).read_bytes()).decode() if (Path('/app')/n).is_file() else None for n in "+repr(names)+"}))"
 rows=json.loads(subprocess.check_output(['docker','exec',CONTAINERS[service],'python','-c',pcode]))
 result['files'][service]=rows
 result['baselines'][service]={n:hashlib.sha256(base64.b64decode(v)).hexdigest() if v is not None else None for n,v in rows.items()}
for name in ('compose.yaml','compose.paper-search.yaml','.env','.env.reader'):
 result['config_hashes'][name]=hashlib.sha256((Path('/opt/space-news')/name).read_bytes()).hexdigest()
print(json.dumps(result))
'''
    code = 'GROUPS=' + repr(GROUPS) + '\nCONTAINERS=' + repr(CONTAINERS) + '\n' + code
    result = subprocess.run(['ssh', '-i', str(ROOT.parent/'GPT.pem'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
                             'root@8.137.164.100', 'python3', '-'], input=code.encode(), stdout=subprocess.PIPE, check=True)
    state = json.loads(result.stdout)
    OUT.mkdir(parents=True, exist_ok=True)
    for service, files in state.pop('files').items():
        for name, blob in files.items():
            if blob is not None:
                path = OUT/'baseline'/service/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(blob))
    (OUT/'preflight.json').write_text(json.dumps(state, indent=2))
    print(json.dumps({'healthy_services':list(state['containers']), 'baselines_captured':sum(map(len,state['baselines'].values()))}))


if __name__ == '__main__':
    main()
