"""Server deployment: preserve each live service, shared private config, and rollback."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/opt/space-news')
NAMES={'app':'space-news-app-1','admin':'space-news-admin-1','reader':'space-news-paper-search'}


def run(*args):return subprocess.check_output(args,cwd=PROJECT,text=True)
def inspect(name):return json.loads(run('docker','inspect',name))[0]
def sha(data):return hashlib.sha256(data).hexdigest()
def credential_name(name):
    if name in {'GPG_KEY','PYTHON_GPG_KEY'}:return False  # Public vendor signing-key fingerprints.
    if name.endswith(('_FILE','_PATH')):return False
    return bool(re.search(r'API_KEY|APP_KEY|SECRET|PASSWORD|(?:^|_)KEY$|(?:^|_)(?:ACCESS_TOKEN|AUTH_TOKEN|INSTTOKEN|TOKEN)$|CREDENTIALS$',name,re.I))
def get(url):
    with urlopen(url,timeout=20) as response:return response.read()


def compose(main,reader):
    run('docker','compose','-p','space-news','-f',str(main),'--profile','review','up','-d','--no-build','--no-deps','app','admin')
    run('docker','compose','-p','space-news-paper-search','-f',str(reader),'up','-d','--no-build','--no-deps','reader')


def healthy():
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        if all(inspect(name)['State'].get('Health',{}).get('Status')=='healthy' for name in NAMES.values()):return
        time.sleep(2)
    raise RuntimeError('A service did not become healthy')


def replace_images(text,images):
    lines=text.splitlines();service=None
    for i,line in enumerate(lines):
        match=re.fullmatch(r'  ([A-Za-z0-9_-]+):',line)
        if match:service=match[1]
        if service in images and re.match(r'^    image:',line):lines[i]='    image: '+images[service]
    return '\n'.join(lines)+'\n'


def main():
    assert os.geteuid()==0
    manifest=json.loads((ROOT/'manifest.json').read_text())
    assert sha((ROOT/'release.tar.gz').read_bytes())==manifest['archive_sha256']
    before={role:inspect(name) for role,name in NAMES.items()}
    for role,item in before.items():
        assert item['Id']==manifest['containers'][role]['id'],'Container changed since preflight'
        assert item['State']['Health']['Status']=='healthy'
    for name,digest in manifest['config_hashes'].items():assert sha((PROJECT/name).read_bytes())==digest,'Config changed: '+name
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
    (evidence/'container-inspect.private.json').write_text(json.dumps(before))
    (evidence/'container-inspect.private.json').chmod(0o600)
    stage=evidence/'stage';stage.mkdir()
    with tarfile.open(ROOT/'release.tar.gz') as archive:
        members=archive.getmembers()
        assert {m.name for m in members}==set(manifest['files']) and len(members)==len(manifest['files'])
        for member in members:
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            blob=archive.extractfile(member).read();assert sha(blob)==manifest['files'][member.name]
            path=stage/member.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
    # Check every touched live file before creating snapshots or modifying anything.
    for role,files in manifest['groups'].items():
        code="from pathlib import Path;import hashlib,json;print(json.dumps({n:hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest() if (Path('/app')/n).is_file() else None for n in "+repr(files)+"}))"
        actual=json.loads(run('docker','exec',NAMES[role],'python','-c',code))
        assert actual==manifest['baselines'][role],'Live source changed since preflight: '+role
    # Back up the management DB transactionally; never copy a live SQLite main file alone.
    backup='/data/api-management-before-'+stamp
    code="import sqlite3;from pathlib import Path;p=Path("+repr(backup)+");p.mkdir(mode=0o700);\nfor name in ('site-management.sqlite3','news.sqlite3','ai.sqlite3'):\n source=Path('/data')/name\n if source.exists():\n  with sqlite3.connect(str(source)) as a,sqlite3.connect(str(p/name)) as b:a.backup(b)\nprint('Database snapshots saved')"
    run('docker','exec',NAMES['admin'],'python','-c',code)
    run('docker','cp',NAMES['admin']+':'+backup,str(evidence/'databases'))
    originals={}
    for name in manifest['files']:
        target=PROJECT/name;originals[name]=target.read_bytes() if target.is_file() else None
        if originals[name] is not None:
            saved=evidence/'source'/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(originals[name])
    main_path=PROJECT/'compose.yaml';reader_path=PROJECT/'compose.paper-search.yaml'
    main_before=main_path.read_text();reader_before=reader_path.read_text()
    (evidence/'compose.before.yaml').write_text(main_before)
    (evidence/'compose.reader.before.yaml').write_text(reader_before)
    settings_code="from backend import management_store as s;import json;\nwith s.connection() as d:\n print(json.dumps({'ai':list(d.execute('SELECT revision,desired_version FROM ai_config_state WHERE id=1').fetchone()),'resources':d.execute('SELECT COUNT(*) FROM resource_items').fetchone()[0]}))"
    settings_before=run('docker','exec',NAMES['admin'],'python','-c',settings_code)
    health_before=json.loads(get('https://8.137.164.100:8080/api/health'))
    ai_before=json.loads(get('https://8.137.164.100:8080/api/ai/status'))
    images,rollback={},{}
    for role,files in manifest['groups'].items():
        rollback[role]='space-news-before-api-management-'+role+':'+stamp
        # Capture actual live files, because old services intentionally have
        # different baselines. Strip runtime credentials from snapshot metadata.
        changes=[]
        for entry in before[role]['Config'].get('Env',[]):
            name=entry.partition('=')[0]
            if credential_name(name):
                changes+=['--change','ENV '+name+'=']
        run('docker','commit',*changes,NAMES[role],rollback[role])
        images[role]='space-news-api-management-'+role+':'+stamp
        dockerfile=stage/('Dockerfile.'+role)
        dockerfile.write_text('FROM '+rollback[role]+'\nUSER 0\n'+''.join('COPY '+n+' /app/'+n+'\n' for n in files)+'USER '+(before[role]['Config'].get('User') or '0')+'\n')
        run('docker','build','--pull=false','-f',str(dockerfile),'-t',images[role],str(stage))
        image=json.loads(run('docker','image','inspect',images[role]))[0]
        for entry in image['Config'].get('Env',[]):
            name,_,value=entry.partition('=')
            assert not (value and credential_name(name)),'Credential remained in image metadata'
        module={'app':'backend.app','admin':'backend.admin_app','reader':'reader.app'}[role]
        run('docker','run','--rm','--network','none',images[role],'python','-c','import '+module)
    data_mount=next(m for m in before['app']['Mounts'] if m['Destination']=='/data')
    key_mount=next(m for m in before['app']['Mounts'] if m['Destination']=='/run/secrets/site-management.key')
    assert data_mount['Type']=='volume' and not key_mount['RW']
    def reader_config(text,image):
        text=replace_images(text,{'reader':image})
        assert '      READER_PUBLIC_ORIGIN:' in text and '    volumes:' not in text
        text=text.replace('    ports:\n','    volumes:\n      - api-management-data:/data\n      - '+key_mount['Source']+':/run/secrets/site-management.key:ro\n    ports:\n',1)
        lines=text.splitlines();index=next(i for i,v in enumerate(lines) if v.startswith('      READER_PUBLIC_ORIGIN:'))
        lines[index+1:index+1]=['      MANAGEMENT_DB_PATH: /data/site-management.sqlite3','      AI_MASTER_KEY_FILE: /run/secrets/site-management.key']
        return '\n'.join(lines)+'\nvolumes:\n  api-management-data:\n    external: true\n    name: '+data_mount['Name']+'\n'
    metadata={'images':images,'rollback_images':rollback,'evidence':str(evidence)}
    (evidence/'rollback.json').write_text(json.dumps(metadata,indent=2))
    changed=False
    try:
        changed=True
        for name in manifest['files']:
            target=PROJECT/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,target)
        main_path.write_text(replace_images(main_before,{k:images[k] for k in ('app','admin')}))
        reader_path.write_text(reader_config(reader_before,images['reader']))
        run('docker','compose','-p','space-news','-f',str(main_path),'--profile','review','config','--quiet')
        run('docker','compose','-p','space-news-paper-search','-f',str(reader_path),'config','--quiet')
        compose(main_path,reader_path);healthy()
        for role,name in NAMES.items():
            prior=dict(v.split('=',1) for v in before[role]['Config'].get('Env',[]))
            actual=dict(v.split('=',1) for v in inspect(name)['Config'].get('Env',[]))
            for field,value in prior.items():
                if value and credential_name(field):
                    assert actual.get(field)==value,'Existing credential environment changed: '+role+'/'+field
        assert run('docker','exec',NAMES['admin'],'python','-c',settings_code)==settings_before,'Existing settings changed'
        # Initialization is additive, disabled by default and makes no network call.
        run('docker','exec',NAMES['admin'],'python','-c',"from backend import literature_config as c;c.initialize('deployment-20261020');print('Literature management initialized')")
        deadline=time.monotonic()+20
        status=None
        while time.monotonic()<deadline:
            code="from backend import literature_config as c;import json;print(json.dumps(c.overview()))"
            status=json.loads(run('docker','exec',NAMES['admin'],'python','-c',code))
            if all(p['status']=='applied' for p in status['providers']):break
            time.sleep(1)
        assert status and all(p['status']=='applied' for p in status['providers']),'Reader did not acknowledge managed configuration'
        checked=0
        for name in manifest['files']:
            if name.startswith('web/'):
                assert sha(get('https://8.137.164.100:8080/assets/'+name[4:]))==manifest['files'][name];checked+=1
            elif name.startswith('admin_web/'):
                suffix='' if name.endswith('/index.html') else name[10:]
                assert sha(get('http://127.0.0.1:8090/'+suffix))==manifest['files'][name];checked+=1
        for role,files in manifest['groups'].items():
            code="from pathlib import Path;import hashlib,json;print(json.dumps({n:hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest() for n in "+repr(files)+"}))"
            actual=json.loads(run('docker','exec',NAMES[role],'python','-c',code))
            assert all(actual[n]==manifest['files'][n] for n in files)
        assert json.loads(get('https://8.137.164.100:8080/api/ai/status'))==ai_before
        assert json.loads(get('https://8.137.164.100:8080/api/health'))['articles']>=health_before['articles']
        retained="import sqlite3;\na=sqlite3.connect("+repr(backup+'/news.sqlite3')+");b=sqlite3.connect('/data/news.sqlite3');prior=a.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles').fetchall();current={r[0]:r[1:] for r in b.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles')};assert all(current.get(r[0])==r[1:] for r in prior);print('Historical article identities retained')"
        run('docker','exec',NAMES['app'],'python','-c',retained)
        assert json.loads(get('https://8.137.164.100:8080/api/reader/health'))['service']=='paper-search'
        # Private management routes must not be exposed through the public site.
        import urllib.error
        try:get('https://8.137.164.100:8080/api/literature-config')
        except urllib.error.HTTPError as error:assert error.code==404
        else:raise AssertionError('Private management route exposed')
        result={**metadata,'status':'deployed','static_urls_checked':checked,
                'knowledge_settings_unchanged':True,'resources_unchanged':True,
                'provider_states':[{k:p[k] for k in ('provider','status','loaded_version')} for p in status['providers']],
                'reader_config':json.loads(get('https://8.137.164.100:8080/api/reader/config'))}
        (ROOT/'result.json').write_text(json.dumps(result,indent=2))
        (evidence/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    except BaseException:
        if changed:
            for name,blob in originals.items():
                target=PROJECT/name
                if blob is None:target.unlink(missing_ok=True)
                else:target.write_bytes(blob)
            main_path.write_text(replace_images(main_before,{k:rollback[k] for k in ('app','admin')}))
            reader_path.write_text(replace_images(reader_before,{'reader':rollback['reader']}))
            compose(main_path,reader_path);healthy()
            print('Rolled back services; private evidence retained at '+str(evidence),flush=True)
        raise


if __name__=='__main__':main()
