"""Read-only production preflight. Never exports container secrets or configuration values."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/api-management-release-20261020'
CONTAINERS={'app':'space-news-app-1','admin':'space-news-admin-1','reader':'space-news-paper-search'}
FILES=['backend/admin_app.py','backend/literature_admin.py','backend/literature_config.py','reader/__init__.py',
       'admin_web/index.html','admin_web/admin.css','admin_web/admin.js','admin_web/ai-settings.js','admin_web/api-settings.js',
       'reader/app.py','reader/config.py','reader/discovery.py','reader/wanfang.py','reader/sciencedirect.py','reader/provider_runtime.py',
       'web/research.html','web/research.css','web/research.js']


def main():
    code='CONTAINERS='+repr(CONTAINERS)+'\nFILES='+repr(FILES)+'\n'+'''import base64,hashlib,json,subprocess
from pathlib import Path
result={'containers':{},'files':{},'config_hashes':{},'shared_code':{}}
for service,name in CONTAINERS.items():
 d=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
 assert d['State']['Health']['Status']=='healthy', service
 result['containers'][service]={'id':d['Id'],'image':d['Image'],'tag':d['Config']['Image'],
   'compose_service':d['Config'].get('Labels',{}).get('com.docker.compose.service'),
   'mounts':[{k:m.get(k) for k in ('Type','Name','Source','Destination','RW')} for m in d['Mounts']],
   'environment_names':[v.split('=',1)[0] for v in d['Config'].get('Env',[])]}
 pcode="from pathlib import Path;import base64,json;print(json.dumps({n:base64.b64encode((Path('/app')/n).read_bytes()).decode() if (Path('/app')/n).is_file() else None for n in "+repr(FILES)+"}))"
 result['files'][service]=json.loads(subprocess.check_output(['docker','exec',name,'python','-c',pcode]))
 pcode="from pathlib import Path;import hashlib,json;print(json.dumps({str(p.relative_to('/app')):hashlib.sha256(p.read_bytes()).hexdigest() for root in ('backend','admin_web') for p in (Path('/app')/root).rglob('*') if p.is_file() and '__pycache__' not in p.parts}))"
 result['shared_code'][service]=json.loads(subprocess.check_output(['docker','exec',name,'python','-c',pcode]))
for name in ('compose.yaml','compose.paper-search.yaml','.env','.env.reader'):
 result['config_hashes'][name]=hashlib.sha256((Path('/opt/space-news')/name).read_bytes()).hexdigest()
result['compose_paper']=base64.b64encode(Path('/opt/space-news/compose.paper-search.yaml').read_bytes()).decode()
print(json.dumps(result))
'''
    response=subprocess.run(['ssh','-i',str(ROOT.parent/'GPT.pem'),'-o','BatchMode=yes','-o','ConnectTimeout=12',
                             'root@8.137.164.100','python3','-'],input=code.encode(),stdout=subprocess.PIPE,check=True)
    result=json.loads(response.stdout);OUT.mkdir(parents=True,exist_ok=True)
    for service,files in result.pop('files').items():
        for name,value in files.items():
            if value is None:continue
            target=OUT/'baseline'/service/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(base64.b64decode(value))
    (OUT/'compose.paper-search.before.yaml').write_bytes(base64.b64decode(result.pop('compose_paper')))
    (OUT/'preflight.json').write_text(json.dumps(result,indent=2))
    differences={name:(result['shared_code']['app'].get(name),result['shared_code']['admin'].get(name))
                 for name in set(result['shared_code']['app'])|set(result['shared_code']['admin'])
                 if result['shared_code']['app'].get(name)!=result['shared_code']['admin'].get(name)}
    print(json.dumps({'healthy':list(result['containers']),'app_admin_shared_differences':list(differences),
                      'reader_mounts':result['containers']['reader']['mounts'],
                      'reader_service':result['containers']['reader']['compose_service']}))


if __name__=='__main__':main()
