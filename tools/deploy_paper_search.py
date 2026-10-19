"""Server-only paper search release with verified baselines and rollback."""
import hashlib,json,os,re,shutil,subprocess,tarfile,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from deploy_news_switch import files,inspect,settings_state,wait_healthy,get

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/opt/space-news')
NGINX=Path('/etc/nginx/sites-enabled/space-news-mcp').resolve()
SNIPPET=Path('/etc/nginx/snippets/space-paper-search.conf')
COMPOSE=PROJECT/'compose.paper-search.yaml'
ENV=PROJECT/'.env.reader'

def run(*args,capture=False):
    p=subprocess.run(args,cwd=PROJECT,check=True,text=True,stdout=subprocess.PIPE if capture else None)
    return p.stdout

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    assert os.geteuid()==0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
    manifest=json.loads((ROOT/'manifest.json').read_text())
    assert digest(ROOT/'release.tar.gz')==manifest['archive_sha256']
    stage=evidence/'stage';stage.mkdir()
    with tarfile.open(ROOT/'release.tar.gz') as archive:
        members=archive.getmembers()
        assert len(members)==len(manifest['files']) and {m.name for m in members}==set(manifest['files'])
        for m in members:
            assert m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
            data=archive.extractfile(m).read();assert hashlib.sha256(data).hexdigest()==manifest['files'][m.name]
            dest=stage/m.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);dest.chmod(0o644)
    before=inspect('app');admin=inspect('admin')['Id'];original=files('app')
    assert before['State']['Health']['Status']=='healthy'
    assert before['Config']['Labels']['com.docker.compose.project']=='space-news'
    for name,value in manifest['baselines'].items():assert original[name]==value,'Online baseline changed: '+name
    state_before=settings_state();assert not any(x['pending'] for x in state_before['ledgers'].values())
    ai_before=get(18081,'/api/ai/status');health_before=get(18081,'/api/health')
    old_nginx=NGINX.read_bytes()
    assert 'listen 8080 ssl;' in old_nginx.decode() and 'space-paper-search' not in old_nginx.decode()
    assert not COMPOSE.exists() and not SNIPPET.exists(),'An existing paper-search deployment requires an update plan'
    assert not run('docker','ps','-aq','--filter','name=^space-news-paper-search$',capture=True).strip()
    old_source={}
    for name in manifest['files']:
        if name.startswith('web/'):
            source=PROJECT/name;old_source[name]=source.read_bytes() if source.exists() else None
            target=evidence/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True)
            if name in original:run('docker','cp',before['Id']+':/app/'+name,str(target))
    (evidence/'nginx.conf').write_bytes(old_nginx)
    # Snapshot contains current hot-deployed files, but excludes environment secrets.
    snapshot='space-news-before-paper-search:'+stamp
    changes=[]
    for entry in before['Config'].get('Env',[]):
        name=entry.partition('=')[0]
        if re.search('KEY|SECRET|PASSWORD|TOKEN',name) and not name.endswith(('_FILE','_PATH')):
            changes+=['--change','ENV '+name+'=']
    run('docker','commit',*changes,before['Id'],snapshot)
    image='space-news-paper-search:'+stamp
    user=before['Config'].get('User') or '0';assert re.fullmatch(r'[\w:.-]+',user)
    (stage/'Dockerfile').write_text('FROM '+snapshot+'\nUSER 0\nCOPY web/ /app/web/\nCOPY reader/ /app/reader/\nCOPY reader_web/ /app/reader_web/\nUSER '+user+'\n')
    run('docker','build','--pull=false','-t',image,str(stage))
    run('docker','run','--rm','--network','none',image,'python','-c',
        'import reader.app,reader.discovery; print("Paper service imports verified")')
    newenv=not ENV.exists()
    changed=False
    metadata={'image':image,'rollback_image':snapshot,'evidence':str(evidence),'main_container':before['Id'],'admin_container':admin}
    (evidence/'rollback.json').write_text(json.dumps(metadata,indent=2))
    try:
        changed=True
        if newenv:
            assert (ROOT/'.env.reader').exists()
            ENV.write_bytes((ROOT/'.env.reader').read_bytes());ENV.chmod(0o600)
        compose='''name: space-news-paper-search
services:
  reader:
    image: IMAGE
    container_name: space-news-paper-search
    command: [python, -m, uvicorn, 'reader.app:app', --host, '0.0.0.0', --port, '8002', --workers, '1', --no-proxy-headers]
    env_file: .env.reader
    environment:
      READER_PUBLIC_ORIGIN: https://8.137.164.100:8080
    ports:
      - '127.0.0.1:8092:8002'
    mem_limit: 256m
    cpus: 0.5
    restart: unless-stopped
    healthcheck:
      test: [CMD, python, '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/api/reader/health',timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: 5m
        max-file: '3'
'''.replace('IMAGE',image)
        COMPOSE.write_text(compose)
        run('docker','compose','-f',str(COMPOSE),'config','--quiet')
        run('docker','compose','-f',str(COMPOSE),'up','-d','--no-build','--pull','never')
        for _ in range(45):
            try:
                assert get(8092,'/api/reader/health')['service']=='paper-search';break
            except Exception:time.sleep(1)
        else:raise RuntimeError('New service failed health check')
        snippet='''location = /reader { return 308 /reader/; }
location /reader/ {
    proxy_pass http://127.0.0.1:8092;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 90s;
}
location /reader-assets/ {
    proxy_pass http://127.0.0.1:8092;
    proxy_set_header Host $http_host;
}
location /api/reader/ {
    proxy_pass http://127.0.0.1:8092;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 90s;
    proxy_buffering off;
    proxy_cache off;
}
'''
        SNIPPET.parent.mkdir(exist_ok=True);SNIPPET.write_text(snippet)
        text=old_nginx.decode();position=text.index('listen 8080 ssl;');offset=text.index('    location / {',position)
        text=text[:offset]+'    include /etc/nginx/snippets/space-paper-search.conf;\n'+text[offset:]
        NGINX.write_text(text);run('nginx','-t');run('systemctl','reload','nginx')
        # Stable image tag and server source also contain the release for future recreation.
        run('docker','tag',image,before['Config']['Image'])
        for name in manifest['files']:
            target=PROJECT/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,target)
        names=[n for n in manifest['files'] if n.startswith('web/') and n!='web/index.html']+['web/index.html']
        for name in names:run('docker','cp',str(stage/name),before['Id']+':/app/'+name)
        actual=files('app')
        assert all(actual.get(n)==h for n,h in original.items() if n not in manifest['files']),'Unrelated main-site file changed'
        assert all(actual[n]==manifest['files'][n] for n in names)
        wait_healthy('app')
        assert inspect('app')['Id']==before['Id'] and inspect('admin')['Id']==admin
        assert get(18081,'/api/ai/status')==ai_before
        assert get(18081,'/api/health')['articles']>=health_before['articles']
        assert settings_state()==state_before
        public='https://8.137.164.100:8080'
        with urllib.request.urlopen(public+'/reader/',timeout=15) as response:
            assert hashlib.sha256(response.read()).hexdigest()==manifest['files']['reader_web/index.html']
        with urllib.request.urlopen(public+'/api/reader/health',timeout=15) as response:
            assert json.load(response)['service']=='paper-search'
        for name in names:
            url=public+('/' if name=='web/index.html' else '/assets/'+name[4:])
            with urllib.request.urlopen(url,timeout=15) as response:
                assert hashlib.sha256(response.read()).hexdigest()==manifest['files'][name],name
        result={**metadata,'status':'deployed','public':public+'/reader/','articles':get(18081,'/api/health')['articles'],
                'main_restarted':False,'admin_unchanged':True,'settings_unchanged':True}
        (ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    except BaseException:
        if changed:
            NGINX.write_bytes(old_nginx);SNIPPET.unlink(missing_ok=True);run('nginx','-t');run('systemctl','reload','nginx')
            run('docker','tag',before['Image'],before['Config']['Image'])
            for name in manifest['files']:
                if not name.startswith('web/'):continue
                saved=evidence/'runtime'/name
                if saved.exists():run('docker','cp',str(saved),before['Id']+':/app/'+name)
                else:
                    run('docker','exec','-u','0',before['Id'],'python','-c','from pathlib import Path;Path('+repr('/app/'+name)+').unlink(missing_ok=True)')
                target=PROJECT/name
                if old_source[name] is None:target.unlink(missing_ok=True)
                else:target.write_bytes(old_source[name])
            if COMPOSE.exists():run('docker','compose','-f',str(COMPOSE),'down')
            COMPOSE.unlink(missing_ok=True)
            if newenv:ENV.unlink(missing_ok=True)
        raise

if __name__=='__main__':main()
