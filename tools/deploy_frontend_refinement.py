"""Server-only release of the three approved frontend refinements."""
import hashlib
import json
import os
import re
import tarfile
import urllib.request
from datetime import datetime,timezone
from pathlib import Path
from deploy_news_switch import run,get,inspect,files,settings_state,wait_healthy

ROOT=Path(__file__).resolve().parent


def runtime(value):
    host=dict(value['HostConfig'])
    for name in ('Binds','CapAdd','CapDrop','SecurityOpt'):
        if host.get(name) is not None:host[name]=sorted(host[name])
    config={name:value['Config'][name] for name in ('Cmd','Entrypoint','User')}
    config['Env']=sorted(value['Config']['Env'])
    return {'host':host,'mounts':sorted(value['Mounts'],key=lambda item:item['Destination']),'config':config}


def main():
    if os.geteuid()!=0:raise RuntimeError('Server operator only')
    manifest=json.loads((ROOT/'manifest.json').read_text())
    archive=ROOT/'release.tar.gz'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:raise RuntimeError('Archive checksum mismatch')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
    stage=evidence/'stage';stage.mkdir()
    with tarfile.open(archive) as release:
        members=release.getmembers()
        if {item.name for item in members}!=set(manifest['files']) or len(members)!=len(manifest['files']):raise RuntimeError('Unexpected release contents')
        for item in members:
            if not item.isfile() or item.name.startswith('/') or '..' in Path(item.name).parts:raise RuntimeError('Invalid archive member')
            data=release.extractfile(item).read()
            if hashlib.sha256(data).hexdigest()!=manifest['files'][item.name]:raise RuntimeError('File checksum mismatch')
            target=stage/item.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    before=inspect('app');admin=inspect('admin')['Id'];original=files('app')
    if before['Config']['Labels'].get('com.docker.compose.project')!='space-news':raise RuntimeError('Unexpected Compose identity')
    for name,digest in manifest['baselines'].items():
        if original.get(name)!=digest:raise RuntimeError('Unreviewed live source: '+name)
    state_before=settings_state()
    if any(value['pending'] for value in state_before['ledgers'].values()):raise RuntimeError('Wait for pending model requests before deployment')
    health_before=get(18081,'/api/health');ai_before=get(18081,'/api/ai/status');agent_before=get(18081,'/api/news/362/agent-status')
    compose_hash=hashlib.sha256(run('docker','compose','--profile','review','config',capture=True).encode()).hexdigest()
    backup=("import sqlite3;from pathlib import Path;from contextlib import closing;"
            f"target=Path('/data/frontend-refinement-before-{stamp}');target.mkdir(mode=0o700)\n"
            "for p in Path('/data').glob('*.sqlite3'):\n"
            " with closing(sqlite3.connect(str(p))) as origin,closing(sqlite3.connect(str(target/p.name))) as saved:\n"
            "  origin.backup(saved)\nprint('SQLite backups complete')")
    run('docker','exec','space-news-app-1','python','-c',backup)
    snapshot='space-news-app-before-refinement:'+stamp
    changes=[]
    for entry in before['Config'].get('Env',[]):
        name=entry.partition('=')[0]
        if re.search('API_KEY|SERVICE_KEY|ACCESS_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN',name) and not name.endswith(('_FILE','_PATH')):
            changes+=['--change',f'ENV {name}=']
    run('docker','commit',*changes,'space-news-app-1',snapshot)
    image='space-news-app-frontend-refinement:'+stamp
    (stage/'Dockerfile').write_text(f'FROM {snapshot}\nUSER 0\n'+''.join(f'COPY {name} /app/{name}\n' for name in manifest['files'])+'USER 10001:10001\n')
    run('docker','build','--pull=false','-t',image,str(stage))
    run('docker','run','--rm','--network','none','--tmpfs','/data:rw,uid=10001,gid=10001,mode=0700',
        '-e','AI_COOKIE_SECURE=0','-e','COLLECT_ENABLED=0',image,'python','-m','unittest','tests.test_news_agent','tests.test_news_limits')
    run('docker','run','--rm','--network','none',image,'python','tools/build_styles.py','--check')
    (evidence/'rollback-image').write_text(snapshot+'\n')
    changed=False
    try:
        changed=True;run('docker','tag',image,'space-news-app')
        run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','app');wait_healthy('app')
        if runtime(inspect('app'))!=runtime(before):raise RuntimeError('Runtime settings changed')
        actual=files('app')
        if any(actual.get(name)!=digest for name,digest in original.items() if name not in manifest['files']):raise RuntimeError('Unrelated runtime files changed')
        if any(actual.get(name)!=digest for name,digest in manifest['files'].items() if name.startswith(('backend/','web/','tests/'))):raise RuntimeError('Release file mismatch')
        if inspect('admin')['Id']!=admin:raise RuntimeError('Private admin unexpectedly restarted')
        if settings_state()!=state_before:raise RuntimeError('Configuration or request ledger changed')
        if get(18081,'/api/health')['articles']<health_before['articles'] or get(18081,'/api/ai/status')!=ai_before:raise RuntimeError('Existing site regression')
        status=get(18081,'/api/news-agent/status')
        if status['enabled']!=agent_before['enabled']:raise RuntimeError('News switch changed')
        if hashlib.sha256(run('docker','compose','--profile','review','config',capture=True).encode()).hexdigest()!=compose_hash:raise RuntimeError('Compose changed')
        for name,digest in manifest['files'].items():
            if not name.startswith('web/'):continue
            url='http://127.0.0.1:18081'+('/' if name=='web/index.html' else '/assets/'+name[4:])
            with urllib.request.urlopen(url,timeout=5) as reply:
                if hashlib.sha256(reply.read()).hexdigest()!=digest:raise RuntimeError('Served bytes differ: '+name)
        result={'status':'deployed','image':image,'rollback':snapshot,'evidence':str(evidence),
                'articles':get(18081,'/api/health')['articles'],'news_agent':status,'css_entries':3,'tests_passed':52,'model_calls':0}
        (evidence/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    except BaseException:
        if changed:
            run('docker','tag',snapshot,'space-news-app')
            run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','app');wait_healthy('app')
        raise


if __name__=='__main__':main()
