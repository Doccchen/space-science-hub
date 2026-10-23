"""Verified incremental guide release with live-image, source and database backups."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from deploy_news_switch import settings_state

PROJECT = Path('/opt/space-news')
ROOT = Path(__file__).resolve().parent
CONTAINERS = {s:'space-news-'+s+'-1' for s in ('app','admin')}


def run(*args):
    return subprocess.check_output(args, cwd=PROJECT, text=True)


def digest(blob): return hashlib.sha256(blob).hexdigest()
def inspect(s): return json.loads(run('docker','inspect',CONTAINERS[s]))[0]


def hashes(s, image=None):
    code = "from pathlib import Path;import hashlib,json;print(json.dumps({str(p.relative_to('/app')):hashlib.sha256(p.read_bytes()).hexdigest() for r in ('backend','web','admin_web','reader','reader_web','tests') for p in (Path('/app')/r).rglob('*') if p.is_file() and '__pycache__' not in p.parts}))"
    prefix = ['docker','run','--rm','--network','none',image] if image else ['docker','exec',CONTAINERS[s]]
    return json.loads(run(*prefix,'python','-c',code))


def config_hashes():
    return {name:digest((PROJECT/name).read_bytes()) for name in ('compose.yaml','compose.paper-search.yaml','.env','.env.reader')}


def get(url):
    with urllib.request.urlopen(url,timeout=20) as response: return response.read()


def wait_healthy():
    deadline = time.monotonic()+100
    while time.monotonic()<deadline:
        if all(inspect(s)['State'].get('Health',{}).get('Status')=='healthy' for s in CONTAINERS): return
        time.sleep(2)
    raise RuntimeError('Services did not recover health')


def configuration(state): return {k:v for k,v in state.items() if k!='ledgers'}


def main():
    assert os.geteuid()==0
    manifest = json.loads((ROOT/'manifest.json').read_text())
    assert digest((ROOT/'release.tar.gz').read_bytes())==manifest['archive_sha256']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = ROOT/stamp; evidence.mkdir(mode=0o700)
    stage = evidence/'stage'; stage.mkdir()
    with tarfile.open(ROOT/'release.tar.gz') as archive:
        members = archive.getmembers()
        assert len(members)==len(manifest['files']) and {m.name for m in members}==set(manifest['files'])
        for member in members:
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            blob = archive.extractfile(member).read(); assert digest(blob)==manifest['files'][member.name]
            target = stage/member.name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(blob); target.chmod(0o644)
    groups = manifest['groups']; before = {s:inspect(s) for s in groups}
    original = {s:hashes(s) for s in groups}
    state = settings_state(); config = config_hashes()
    assert not any(v['pending'] for v in state['ledgers'].values()), 'Pending model requests; retry later'
    assert config==manifest['config_hashes'], 'Server configuration changed'
    ai = json.loads(get('http://127.0.0.1:18081/api/ai/status'))
    articles = json.loads(get('http://127.0.0.1:18081/api/health'))['articles']
    old_files,old_source,bases,images,rollback = {},{},{},{},{}
    for name in manifest['files']:
        path = PROJECT/name; blob = path.read_bytes() if path.is_file() else None
        assert (digest(blob) if blob is not None else None)==manifest['source_baselines'][name], 'Source changed: '+name
        old_source[name]=blob
        if blob is not None:
            saved=evidence/'source'/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(blob)
    for s,names in groups.items():
        old=before[s]; assert old['Id']==manifest['containers'][s] and old['State']['Health']['Status']=='healthy'
        for name in names:
            expected=manifest['baselines'][s][name];assert original[s].get(name)==expected,'Live baseline changed: '+s+'/'+name
            saved=evidence/'runtime'/s/name; saved.parent.mkdir(parents=True,exist_ok=True)
            old_files[s,name]=saved if expected is not None else None
            if expected is not None:
                run('docker','cp',old['Id']+':/app/'+name,str(saved));assert digest(saved.read_bytes())==expected
        base=json.loads(run('docker','image','inspect',old['Config']['Image']))[0]['Id']
        assert hashes(s,base)==original[s], 'Image/live drift: '+s
        bases[s]=base;rollback[s]='space-news-before-guides-'+s+':'+stamp;images[s]='space-news-guides-'+s+':'+stamp
        run('docker','tag',base,rollback[s])
        dockerfile=stage/('Dockerfile.'+s)
        dockerfile.write_text('FROM '+base+'\nUSER 0\n'+''.join('COPY '+n+' /app/'+n+'\n' for n in names)+'USER '+(old['Config'].get('User') or '0')+'\n')
        run('docker','build','--pull=false','-f',str(dockerfile),'-t',images[s],str(stage))
        run('docker','run','--rm','--network','none',images[s],'python','-c',"from backend import reading;assert 'markdown' in __import__('inspect').getsource(reading.validate)")
    metadata={'images':images,'rollback':rollback,'tags':{s:d['Config']['Image'] for s,d in before.items()},'containers':{s:d['Id'] for s,d in before.items()},'evidence':str(evidence)}
    (evidence/'rollback.json').write_text(json.dumps(metadata,indent=2))
    backup='/data/guides-before-'+stamp
    backup_code="from pathlib import Path;import sqlite3\nroot=Path("+repr(backup)+");root.mkdir(mode=0o700)\nfor p in Path('/data').glob('*.sqlite3'):\n with sqlite3.connect(p) as src,sqlite3.connect(root/p.name) as dst:src.backup(dst)\n"
    run('docker','exec',CONTAINERS['app'],'python','-c',backup_code)
    run('docker','cp',CONTAINERS['app']+':'+backup,str(evidence/'databases'))
    assert not any(v['pending'] for v in settings_state()['ledgers'].values()), 'Pending requests appeared; retry later'
    changed=False
    try:
        changed=True
        for s,names in groups.items():
            run('docker','tag',images[s],before[s]['Config']['Image'])
            for name in sorted(names,key=lambda n:n.endswith('.html')):
                parent=str(Path('/app')/Path(name).parent)
                run('docker','exec','-u','0',CONTAINERS[s],'python','-c','from pathlib import Path;Path('+repr(parent)+').mkdir(parents=True,exist_ok=True)')
                run('docker','cp',str(stage/name),CONTAINERS[s]+':/app/'+name)
        for name in manifest['files']:
            target=PROJECT/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/name,target)
        run('docker','restart',*CONTAINERS.values());wait_healthy()
        for s,names in groups.items():
            current=inspect(s);assert current['Id']==before[s]['Id']
            assert current['Config']==before[s]['Config'] and current['HostConfig']==before[s]['HostConfig']
            actual=hashes(s)
            assert all(actual.get(n)==h for n,h in original[s].items() if n not in names),'Unrelated file changed'
            assert all(actual.get(n)==manifest['files'][n] for n in names),'Published bytes differ'
            assert hashes(s,images[s])==actual,'Candidate/live image mismatch'
        assert configuration(settings_state())==configuration(state) and config_hashes()==config
        assert json.loads(get('http://127.0.0.1:18081/api/ai/status'))==ai
        assert json.loads(get('http://127.0.0.1:18081/api/health'))['articles']>=articles
        for name in manifest['files']:
            if name.startswith('web/'):
                url='https://8.137.164.100:8080'+('/' if name=='web/index.html' else '/assets/'+name[4:])
                assert digest(get(url))==manifest['files'][name], 'Served bytes differ: '+name
        result={**metadata,'status':'deployed','articles':json.loads(get('http://127.0.0.1:18081/api/health'))['articles'],'configuration_unchanged':True,'database_backup':str(evidence/'databases'),'model_calls':0}
        (evidence/'result.json').write_text(json.dumps(result,indent=2));(ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    except BaseException:
        if changed:
            for s,names in groups.items():
                run('docker','tag',bases[s],before[s]['Config']['Image'])
                for name in names:
                    saved=old_files[s,name]
                    if saved:run('docker','cp',str(saved),CONTAINERS[s]+':/app/'+name)
                    else:run('docker','exec','-u','0',CONTAINERS[s],'python','-c','from pathlib import Path;Path('+repr('/app/'+name)+').unlink(missing_ok=True)')
            for name,blob in old_source.items():
                target=PROJECT/name
                if blob is None:target.unlink(missing_ok=True)
                else:target.write_bytes(blob)
            run('docker','restart',*CONTAINERS.values());wait_healthy()
            print('Release rolled back; evidence: '+str(evidence),flush=True)
        raise


if __name__=='__main__': main()
