"""Copy-only hot release, preserving runtime configuration and rollback images."""
import hashlib,json,os,shutil,subprocess,sys,tarfile,urllib.request
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'/root/paper-search-release-20261019')
from deploy_news_switch import files,get,inspect,settings_state
ROOT=Path(__file__).resolve().parent;PROJECT=Path('/opt/space-news')
def run(*args,capture=False):
 p=subprocess.run(args,cwd=PROJECT,check=True,text=True,stdout=subprocess.PIPE if capture else None);return p.stdout

def main():
 assert os.geteuid()==0
 manifest=json.loads((ROOT/'manifest.json').read_text());archive=ROOT/'release.tar.gz'
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');evidence=ROOT/stamp;evidence.mkdir(mode=0o700);stage=evidence/'stage';stage.mkdir()
 with tarfile.open(archive) as t:
  members=t.getmembers();assert len(members)==len(manifest['files']) and {m.name for m in members}==set(manifest['files'])
  for m in members:
   assert m.isfile() and '..' not in Path(m.name).parts and not m.name.startswith('/')
   blob=t.extractfile(m).read();assert hashlib.sha256(blob).hexdigest()==manifest['files'][m.name]
   p=stage/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob);p.chmod(0o644)
 before={'app':inspect('app'),'reader':json.loads(run('docker','inspect','space-news-paper-search',capture=True))[0]}
 admin=inspect('admin')['Id'];original=files('app');state=settings_state();ai=get(18081,'/api/ai/status')
 groups={'app':[n for n in manifest['files'] if n.startswith('web/')],'reader':[n for n in manifest['files'] if n.startswith('reader_web/')]}
 previous={};source={};images={};rollback={}
 for service,old in before.items():
  assert old['State']['Health']['Status']=='healthy'
  for n in groups[service]:
   target=evidence/'runtime'/n;target.parent.mkdir(parents=True,exist_ok=True);run('docker','cp',old['Id']+':/app/'+n,str(target))
   blob=target.read_bytes();assert hashlib.sha256(blob.replace(b'\r\n',b'\n').removeprefix(b'\xef\xbb\xbf')).hexdigest()==manifest['baselines'][n],n+' baseline changed'
   previous[n]=target;p=PROJECT/n;source[n]=p.read_bytes() if p.is_file() else None
  backup='space-news-before-page-copy-'+service+':'+stamp;run('docker','tag',old['Image'],backup);rollback[service]=backup
  image='space-news-page-copy-'+service+':'+stamp;images[service]=image
  dockerfile=stage/('Dockerfile.'+service)
  dockerfile.write_text('FROM '+old['Image']+'\nUSER 0\n'+''.join('COPY '+n+' /app/'+n+'\n' for n in groups[service])+'USER '+(old['Config'].get('User') or '0')+'\n')
  run('docker','build','--pull=false','-f',str(dockerfile),'-t',image,str(stage))
 (evidence/'rollback.json').write_text(json.dumps({'images':rollback,'tags':{s:b['Config']['Image'] for s,b in before.items()}},indent=2))
 changed=False
 try:
  changed=True
  for service,old in before.items():
   run('docker','tag',images[service],old['Config']['Image'])
   for n in sorted(groups[service],key=lambda n:n.endswith('.html')):
    p=PROJECT/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/n,p)
    run('docker','cp',str(stage/n),old['Id']+':/app/'+n)
  actual=files('app')
  assert all(actual.get(n)==h for n,h in original.items() if n not in manifest['files'])
  for service,old in before.items():
   after=json.loads(run('docker','inspect',old['Id'],capture=True))[0]
   assert after['Config']==old['Config'] and after['HostConfig']==old['HostConfig']
  assert inspect('admin')['Id']==admin and settings_state()==state and get(18081,'/api/ai/status')==ai
  public='https://8.137.164.100:8080'
  for n,h in manifest['files'].items():
   url=public+('/reader/' if n=='reader_web/index.html' else '/' if n=='web/index.html' else '/assets/'+n[4:])
   with urllib.request.urlopen(url,timeout=15) as response:assert hashlib.sha256(response.read()).hexdigest()==h,n
  result={'status':'deployed','images':images,'rollback':rollback,'evidence':str(evidence),'files':len(manifest['files']),'containers_restarted':False,'settings_unchanged':True}
  (ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 except BaseException:
  if changed:
   for service,old in before.items():
    run('docker','tag',old['Image'],old['Config']['Image'])
    for n in groups[service]:
     run('docker','cp',str(previous[n]),old['Id']+':/app/'+n)
     p=PROJECT/n
     if source[n] is None:p.unlink(missing_ok=True)
     else:p.write_bytes(source[n])
  raise
if __name__=='__main__':main()
