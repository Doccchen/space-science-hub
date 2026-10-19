"""Deploy the completed bookshelf without restarting existing services."""
import hashlib,json,os,re,shutil,subprocess,sys,tarfile,urllib.request
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'/root/paper-search-release-20261019')
from deploy_news_switch import inspect,files,settings_state,get,wait_healthy
ROOT=Path(__file__).resolve().parent
PROJECT=Path('/opt/space-news')
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
   assert m.isfile() and m.name.startswith('web/') and '..' not in Path(m.name).parts
   data=t.extractfile(m).read();assert hashlib.sha256(data).hexdigest()==manifest['files'][m.name]
   p=stage/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o644)
 before=inspect('app');admin=inspect('admin')['Id'];original=files('app');state=settings_state();ai=get(18081,'/api/ai/status')
 assert not any(x['pending'] for x in state['ledgers'].values())
 reader=json.loads(run('docker','inspect','space-news-paper-search',capture=True))[0]['Id']
 assert before['State']['Health']['Status']=='healthy'
 # Require the current site to match the baseline captured for this release.
 for n in manifest['files']:
  baseline=ROOT/'baseline-web'/n[4:]
  if baseline.exists():assert original[n]==hashlib.sha256(baseline.read_bytes()).hexdigest(),n
 oldsource={}
 for n in manifest['files']:
  p=PROJECT/n;oldsource[n]=p.read_bytes() if p.exists() else None
  if n in original:
   target=evidence/'runtime'/n;target.parent.mkdir(parents=True,exist_ok=True);run('docker','cp',before['Id']+':/app/'+n,str(target))
 snapshot='space-news-before-bookshelf:'+stamp;changes=[]
 for entry in before['Config'].get('Env',[]):
  name=entry.partition('=')[0]
  if re.search('KEY|SECRET|PASSWORD|TOKEN',name) and not name.endswith(('_FILE','_PATH')):changes+=['--change','ENV '+name+'=']
 run('docker','commit',*changes,before['Id'],snapshot)
 image='space-news-bookshelf:'+stamp;user=before['Config'].get('User') or '0';assert re.fullmatch(r'[\w:.-]+',user)
 (stage/'Dockerfile').write_text('FROM '+snapshot+'\nUSER 0\nCOPY web/ /app/web/\nUSER '+user+'\n')
 run('docker','build','--pull=false','-t',image,str(stage))
 (evidence/'rollback.json').write_text(json.dumps({'snapshot':snapshot,'old_tag':before['Config']['Image'],'old_image':before['Image']},indent=2))
 changed=False
 try:
  changed=True;run('docker','tag',image,before['Config']['Image'])
  names=[n for n in manifest['files'] if not n.endswith('.html')]+[n for n in manifest['files'] if n.endswith('.html')]
  for n in names:
   target=PROJECT/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/n,target)
   run('docker','cp',str(stage/n),before['Id']+':/app/'+n)
  wait_healthy('app');actual=files('app')
  assert all(actual.get(n)==h for n,h in original.items() if n not in manifest['files'])
  assert all(actual[n]==h for n,h in manifest['files'].items())
  assert inspect('app')['Id']==before['Id'] and inspect('admin')['Id']==admin
  assert json.loads(run('docker','inspect','space-news-paper-search',capture=True))[0]['Id']==reader
  assert settings_state()==state and get(18081,'/api/ai/status')==ai
  public='https://8.137.164.100:8080'
  for n,h in manifest['files'].items():
   with urllib.request.urlopen(public+'/assets/'+n[4:],timeout=20) as response:assert hashlib.sha256(response.read()).hexdigest()==h,n
  with urllib.request.urlopen(public+'/api/reader/health',timeout=10) as response:assert json.load(response)['service']=='paper-search'
  result={'status':'deployed','public':public+'/assets/resource-navigation.html','files':len(names),'image':image,'rollback':snapshot,'evidence':str(evidence),'containers_unchanged':True,'settings_unchanged':True,'articles':get(18081,'/api/health')['articles']}
  (ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 except BaseException:
  if changed:
   run('docker','tag',before['Image'],before['Config']['Image'])
   for n in manifest['files']:
    saved=evidence/'runtime'/n
    if saved.exists():run('docker','cp',str(saved),before['Id']+':/app/'+n)
    else:run('docker','exec','-u','0',before['Id'],'python','-c','from pathlib import Path;Path('+repr('/app/'+n)+').unlink(missing_ok=True)')
    target=PROJECT/n
    if oldsource[n] is None:target.unlink(missing_ok=True)
    else:target.write_bytes(oldsource[n])
  raise
if __name__=='__main__':main()
