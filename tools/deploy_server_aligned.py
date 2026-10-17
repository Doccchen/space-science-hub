"""Frontend-only, assets-first hot deployment with image and file rollback."""
import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.request
from datetime import datetime,timezone
from pathlib import Path
from deploy_news_switch import run,get,inspect,files,settings_state,wait_healthy

PROJECT=Path('/opt/space-news')
ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def web_files(root):return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
def configuration(value):
    # Compare in memory; never persist or print environment values.
    return {k:value[k] for k in ['Config','HostConfig','Mounts']}

def main():
    if os.geteuid()!=0:raise RuntimeError('Server operator only')
    archive=ROOT/'server-aligned-local.tar.gz'
    expected=(ROOT/'sha256.txt').read_text().split()[0]
    assert digest(archive)==expected,'Archive checksum mismatch'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
    stage=evidence/'stage';stage.mkdir()
    with tarfile.open(archive) as t:
        members=t.getmembers()
        assert len({m.name for m in members})==len(members)
        assert all(m.isfile() and m.size<=8_000_000 and '..' not in Path(m.name).parts and not m.name.startswith('/') and (m.name in {'manifest.json','tools/build_styles.py'} or m.name.startswith('web/')) for m in members)
        blobs={m.name:t.extractfile(m).read() for m in members}
    manifest=json.loads(blobs['manifest.json'])
    assert manifest['deployable'] is True,'Publication authorization required'
    assert {r['path'] for r in manifest['files']}==set(blobs)-{'manifest.json'}
    for r in manifest['files']:
        assert len(blobs[r['path']])==r['size'] and hashlib.sha256(blobs[r['path']]).hexdigest()==r['sha256']
    additions=json.loads(blobs['web/carousel-additions.json'])
    assert len(additions)==7 and all(s.get('rights_status')=='authorized_user_confirmed' and s.get('rights_evidence') for s in additions)
    before=inspect('app');admin=inspect('admin')['Id'];original=files('app')
    assert before['State']['Health']['Status']=='healthy'
    assert before['Config']['Labels']['com.docker.compose.project']=='space-news'
    for item in manifest['baseline']['files']:
        assert original.get(item['path'])==item['sha256'],'Live baseline changed: '+item['path']
    state_before=settings_state()
    assert not any(v['pending'] for v in state_before['ledgers'].values()),'Pending model requests; retry later'
    health=get(18081,'/api/health');ai=get(18081,'/api/ai/status');agent=get(18081,'/api/news-agent/status')
    source=PROJECT/'web';source_before=web_files(source)
    shutil.copytree(source,evidence/'source-web',symlinks=True)
    run('docker','cp',before['Id']+':/app/web',str(evidence/'runtime-web'))
    source_tool=PROJECT/'tools/build_styles.py'
    tool_existed=source_tool.is_file()
    if tool_existed:shutil.copy2(source_tool,evidence/'source-build-styles.py')
    run('docker','cp',before['Id']+':/app/tools/build_styles.py',str(evidence/'runtime-build-styles.py'))
    for name,blob in blobs.items():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(blob);target.chmod(0o644)
    assets=evidence/'assets';shutil.copytree(stage/'web',assets);(assets/'index.html').unlink()
    snapshot='space-news-app-before-site-update:'+stamp
    changes=[]
    for entry in before['Config'].get('Env',[]):
        name=entry.partition('=')[0]
        if re.search('API_KEY|SERVICE_KEY|ACCESS_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN',name) and not name.endswith(('_FILE','_PATH')):
            changes+=['--change','ENV '+name+'=']
    run('docker','commit',*changes,before['Id'],snapshot)
    image='space-news-app-site-update:'+stamp
    user=before['Config'].get('User') or '0'
    assert re.fullmatch(r'[a-zA-Z0-9_:.-]+',user)
    (stage/'Dockerfile').write_text(f'FROM {snapshot}\nUSER 0\nCOPY web/ /app/web/\nCOPY tools/build_styles.py /app/tools/build_styles.py\nUSER {user}\n')
    run('docker','build','--pull=false','-t',image,str(stage))
    run('docker','run','--rm','--network','none','--tmpfs','/data:rw,uid=10001,gid=10001,mode=0700',
        '-e','AI_COOKIE_SECURE=0','-e','COLLECT_ENABLED=0',image,'python','-m','unittest','tests.test_news_agent','tests.test_news_limits')
    run('docker','run','--rm','--network','none',image,'python','tools/build_styles.py','--check')
    metadata={'archive_sha256':expected,'rollback_image':snapshot,'new_image':image,'running_container':before['Id'],'admin_container':admin}
    (evidence/'rollback.json').write_text(json.dumps(metadata,indent=2))
    names=[r['path'] for r in manifest['files'] if r['path']!='web/index.html']+['web/index.html']
    changed=False
    try:
        changed=True
        run('docker','tag',image,before['Config']['Image'])
        for name in names:
            dest=PROJECT/name;assert dest.is_relative_to(source) or dest==source_tool
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,dest)
        # Copy directory trees once; publish the entry point only after all assets.
        run('docker','cp',str(assets)+'/.',before['Id']+':/app/web/')
        run('docker','cp',str(stage/'tools/build_styles.py'),before['Id']+':/app/tools/build_styles.py')
        run('docker','cp',str(stage/'web/index.html'),before['Id']+':/app/web/index.html')
        # Docker snapshot pause/resume can leave the monitor in "starting" until
        # its next scheduled probe. Require recovery within the existing bound.
        wait_healthy('app')
        actual=files('app')
        tool_digest=run('docker','exec',before['Id'],'python','-c',"import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/app/tools/build_styles.py').read_bytes()).hexdigest())",capture=True).strip()
        actual['tools/build_styles.py']=tool_digest
        for r in manifest['files']:
            assert actual.get(r['path'])==r['sha256'],'Runtime mismatch: '+r['path']
            assert digest(PROJECT/r['path'])==r['sha256'],'Source mismatch: '+r['path']
        assert all(actual.get(n)==h for n,h in original.items() if n.startswith(('backend/','admin_web/','tests/'))),'Backend/admin/test files changed'
        after=inspect('app')
        assert after['Id']==before['Id'] and configuration(after)==configuration(before),'Runtime configuration changed'
        assert inspect('admin')['Id']==admin,'Admin container changed'
        assert after['State']['Health']['Status']=='healthy','App did not recover health'
        assert settings_state()==state_before,'Configuration or request ledgers changed'
        assert get(18081,'/api/ai/status')==ai and get(18081,'/api/news-agent/status')==agent
        assert get(18081,'/api/health').get('articles',0)>=health.get('articles',0)
        run('docker','cp',str(stage/'manifest.json'),before['Id']+':/tmp/site-update-manifest.json')
        code="""import hashlib,json,urllib.request
from pathlib import Path
data=json.loads(Path('/tmp/site-update-manifest.json').read_text())
for r in data['files']:
 if not r['path'].startswith('web/'):continue
 url='http://127.0.0.1:8000'+('/' if r['path']=='web/index.html' else '/assets/'+r['path'][4:])
 with urllib.request.urlopen(url,timeout=15) as response:body=response.read()
 assert hashlib.sha256(body).hexdigest()==r['sha256'],r['path']
print('All served frontend hashes verified:',len(data['files']))
"""
        run('docker','exec',before['Id'],'python','-c',code)
        result={**metadata,'status':'deployed','evidence':str(evidence),'frontend_files':len(manifest['files']),
                'articles':get(18081,'/api/health').get('articles'),'container_restarted':False,
                'backend_unchanged':True,'admin_unchanged':True,'settings_ledgers_unchanged':True,'model_calls':0}
        (ROOT/'deployment-result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    except BaseException:
        if changed:
            run('docker','tag',before['Image'],before['Config']['Image'])
            # Remove only newly added release files; never delete unrelated paths.
            added=[r['path'] for r in manifest['files'] if r['path'].startswith('web/') and r['path'] not in original]
            code='from pathlib import Path\n'+''.join(f'Path({("/app/"+n)!r}).unlink(missing_ok=True)\n' for n in added)
            run('docker','exec','-u','0',before['Id'],'python','-c',code)
            run('docker','cp',str(evidence/'runtime-web')+'/.',before['Id']+':/app/web/')
            run('docker','cp',str(evidence/'runtime-build-styles.py'),before['Id']+':/app/tools/build_styles.py')
            for p in (evidence/'source-web').rglob('*'):
                if p.is_file():
                    dest=source/p.relative_to(evidence/'source-web');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            for name in names:
                if not name.startswith('web/'):continue
                relative=name.removeprefix('web/')
                if relative not in source_before:(PROJECT/name).unlink(missing_ok=True)
            if tool_existed:shutil.copy2(evidence/'source-build-styles.py',source_tool)
            else:source_tool.unlink(missing_ok=True)
        raise

if __name__=='__main__':main()
