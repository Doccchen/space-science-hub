"""Remove news assistant runtime/UI with images, source and proxy rollback."""
import hashlib,json,os,re,shlex,shutil,subprocess,sys,tarfile,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'/root/paper-search-release-20261019')
from deploy_news_switch import inspect,files,settings_state,get,wait_healthy
ROOT=Path(__file__).resolve().parent;PROJECT=Path('/opt/space-news')
def run(*args,capture=False):
 p=subprocess.run(args,cwd=PROJECT,check=True,text=True,stdout=subprocess.PIPE if capture else None);return p.stdout

def main():
 assert os.geteuid()==0
 manifest=json.loads((ROOT/'manifest.json').read_text());archive=ROOT/'release.tar.gz'
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
 stage=evidence/'stage';stage.mkdir()
 with tarfile.open(archive) as t:
  members=t.getmembers();assert len(members)==len(manifest['files']) and {m.name for m in members}==set(manifest['files'])
  for m in members:
   assert m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
   data=t.extractfile(m).read();assert hashlib.sha256(data).hexdigest()==manifest['files'][m.name]
   p=stage/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o644)
 assert all(n.startswith(('backend/','web/','admin_web/','tests/')) and '..' not in Path(n).parts for n in manifest['remove'])
 before={s:inspect(s) for s in ('app','admin')};original={s:files(s) for s in before}
 for n,h in manifest['baselines'].items():assert original['admin' if n=='backend/admin_app.py' else 'app'][n]==h,n
 state=settings_state();assert not any(x['pending'] for x in state['ledgers'].values())
 ai=get(18081,'/api/ai/status');health=get(18081,'/api/health')
 reader=json.loads(run('docker','inspect','space-news-paper-search',capture=True))[0]['Id']
 config=PROJECT/'compose.yaml';oldcompose=config.read_bytes();(evidence/'compose.yaml').write_bytes(oldcompose)
 nginx=Path('/etc/nginx/sites-enabled/space-news-mcp').resolve();oldnginx=nginx.read_bytes();(evidence/'nginx.conf').write_bytes(oldnginx)
 source={}
 for n in list(manifest['files'])+manifest['remove']:
  p=PROJECT/n;source[n]=p.read_bytes() if p.is_file() else None
  if p.is_file():
   backup=evidence/'source'/n;backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(source[n])
 snapshots={};images={}
 for service,old in before.items():
  snapshot='space-news-before-agent-removal-'+service+':'+stamp;changes=[]
  for entry in old['Config'].get('Env',[]):
   name=entry.partition('=')[0]
   if name!='GPG_KEY' and re.search('KEY|SECRET|PASSWORD|TOKEN',name) and not name.endswith(('_FILE','_PATH')):changes+=['--change','ENV '+name+'=']
  run('docker','commit',*changes,old['Id'],snapshot);snapshots[service]=snapshot
  image='space-news-without-news-agent-'+service+':'+stamp;images[service]=image
  user=old['Config'].get('User') or '0';assert re.fullmatch(r'[\w:.-]+',user)
  dockerfile=stage/('Dockerfile.'+service)
  dockerfile.write_text('FROM '+snapshot+'\nUSER 0\n'+''.join('COPY '+n+' /app/'+n+'\n' for n in manifest['files'])+
   'RUN rm -f '+' '.join(shlex.quote('/app/'+n) for n in manifest['remove'])+'\nUSER '+user+'\n')
  run('docker','build','--pull=false','-f',str(dockerfile),'-t',image,str(stage))
  run('docker','run','--rm','--network','none',image,'python','-c','import backend.app,backend.admin_app; print("Retired component imports absent; main/admin imports pass")')
 (evidence/'rollback.json').write_text(json.dumps({'snapshots':snapshots,'tags':{s:b['Config']['Image'] for s,b in before.items()}},indent=2))
 changed=False
 try:
  changed=True
  text=oldcompose.decode();text='\n'.join(line for line in text.splitlines() if not re.match(r'\s+NEWS_(AGENT|MCP|CONTEXT)_',line))+'\n';config.write_text(text)
  text=oldnginx.decode();text,count=re.subn(r'    location = /api/news-mcp/mcp \{.*?\n    \}\n','',text,flags=re.S);assert count==1
  nginx.write_text(text);run('nginx','-t')
  for n in manifest['files']:
   dest=PROJECT/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/n,dest)
  for n in manifest['remove']:(PROJECT/n).unlink(missing_ok=True)
  for s in before:run('docker','tag',images[s],before[s]['Config']['Image'])
  run('docker','compose','--profile','review','config','--quiet')
  run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','app');wait_healthy('app')
  run('docker','compose','--profile','review','up','-d','--no-deps','--no-build','--pull','never','admin');wait_healthy('admin')
  run('systemctl','reload','nginx')
  for s,old in before.items():
   after=inspect(s);actual=files(s)
   assert after['Mounts']==old['Mounts']
   assert all(actual.get(n)==h for n,h in original[s].items() if n not in manifest['files'] and n not in manifest['remove']),s+' unrelated files changed'
   assert all(n not in actual for n in manifest['remove'])
   assert all(actual[n]==h for n,h in manifest['files'].items())
   env=lambda b:{k:v for k,v in (x.split('=',1) for x in b['Config']['Env']) if not k.startswith(('NEWS_AGENT_','NEWS_MCP_','NEWS_CONTEXT_'))}
   assert env(after)==env(old),s+' unrelated environment changed'
  assert get(18081,'/api/ai/status')==ai
  assert get(18081,'/api/health')['articles']>=health['articles']
  assert settings_state()==state
  assert json.loads(run('docker','inspect','space-news-paper-search',capture=True))[0]['Id']==reader
  public='https://8.137.164.100:8080'
  for path in ['/api/news-agent/status','/api/news/1/agent-status','/api/news-agent/jobs/test','/api/news-mcp/mcp','/assets/news-agent.js','/assets/news-agent.css','/assets/news-agent-availability.js']:
   try:urllib.request.urlopen(public+path,timeout=15);raise AssertionError('Retired endpoint active: '+path)
   except urllib.error.HTTPError as error:assert error.code==404,(path,error.code)
  for path in ['/api/news-agent-limits','/news-limits.js']:
   try:urllib.request.urlopen('http://127.0.0.1:8090'+path,timeout=10);raise AssertionError(path)
   except urllib.error.HTTPError as error:assert error.code==404
  for n,h in manifest['files'].items():
   if n.startswith('web/'):
    with urllib.request.urlopen(public+('/' if n=='web/index.html' else '/assets/'+n[4:]),timeout=15) as response:assert hashlib.sha256(response.read()).hexdigest()==h,n
  with urllib.request.urlopen(public+'/api/reader/health',timeout=10) as response:assert json.load(response)['service']=='paper-search'
  result={'status':'deployed','images':images,'rollback':snapshots,'evidence':str(evidence),'articles':get(18081,'/api/health')['articles'],'removed_paths_verified':True,'reader_unchanged':True,'ai_status_unchanged':True,'settings_unchanged':True}
  (ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 except BaseException:
  if changed:
   config.write_bytes(oldcompose);nginx.write_bytes(oldnginx)
   for n,data in source.items():
    p=PROJECT/n
    if data is None:p.unlink(missing_ok=True)
    else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
   for s in before:run('docker','tag',snapshots[s],before[s]['Config']['Image'])
   run('docker','compose','--profile','review','up','-d','--no-deps','--no-build','--pull','never','app','admin')
   wait_healthy('app');wait_healthy('admin');run('nginx','-t');run('systemctl','reload','nginx')
  raise
if __name__=='__main__':main()
