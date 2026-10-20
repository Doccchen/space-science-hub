"""Narrow server-side Wanfang parser release; preserves credentials and provider settings."""
import hashlib
import io
import json
import subprocess
import tarfile
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
PROJECT=Path('/opt/space-news')
NAMES={'admin':'space-news-admin-1','reader':'space-news-paper-search'}


def run(*args):return subprocess.check_output(args,cwd=PROJECT,text=True)
def sha(blob):return hashlib.sha256(blob).hexdigest()
def inspect(name):return json.loads(run('docker','inspect',name))[0]
def config():
    with urlopen('https://8.137.164.100:8080/api/reader/config',timeout=20) as response:return json.load(response)


def restart():
    run('docker','restart',*NAMES.values())
    deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        if all(inspect(n)['State'].get('Health',{}).get('Status')=='healthy' for n in NAMES.values()):return
        time.sleep(2)
    raise RuntimeError('Provider services failed health checks')


def main():
    manifest=json.loads((ROOT/'manifest.json').read_text())
    assert sha((ROOT/'release.tar.gz').read_bytes())==manifest['archive_sha256']
    name='reader/wanfang.py'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence=ROOT/stamp;evidence.mkdir(mode=0o700)
    with tarfile.open(ROOT/'release.tar.gz') as archive:
        members=archive.getmembers();assert len(members)==1 and members[0].name==name and members[0].isfile()
        blob=archive.extractfile(members[0]).read();assert sha(blob)==manifest['new_file_sha256']
    target=evidence/'stage'/name;target.parent.mkdir(parents=True);target.write_bytes(blob)
    before={role:inspect(container) for role,container in NAMES.items()}
    public=config()
    source_before=(PROJECT/name).read_bytes();assert sha(source_before)==manifest['old_file_sha256']
    main_path=PROJECT/'compose.yaml';reader_path=PROJECT/'compose.paper-search.yaml'
    main_before=main_path.read_text();reader_before=reader_path.read_text()
    (evidence/'compose.before.yaml').write_text(main_before);(evidence/'compose.reader.before.yaml').write_text(reader_before)
    snapshots,images,bases={},{},{}
    for role,item in before.items():
        assert item['State']['Health']['Status']=='healthy'
        saved=evidence/(role+'-wanfang.py');run('docker','cp',NAMES[role]+':/app/'+name,str(saved))
        assert sha(saved.read_bytes())==manifest['old_file_sha256']
        bases[role]=json.loads(run('docker','image','inspect',item['Config']['Image']))[0]['Id']
        check="from pathlib import Path;import hashlib;print(hashlib.sha256(Path('/app/reader/wanfang.py').read_bytes()).hexdigest())"
        assert run('docker','run','--rm','--network','none',bases[role],'python','-c',check).strip()==manifest['old_file_sha256']
        snapshots[role]='space-news-before-wanfang-parser-'+role+':'+stamp
        images[role]='space-news-wanfang-parser-'+role+':'+stamp
        run('docker','tag',bases[role],snapshots[role])
        dockerfile=evidence/'stage'/('Dockerfile.'+role)
        dockerfile.write_text('FROM '+bases[role]+'\nUSER 0\nCOPY reader/wanfang.py /app/reader/wanfang.py\nUSER '+(item['Config'].get('User') or '0')+'\n')
        run('docker','build','--pull=false','-f',str(dockerfile),'-t',images[role],str(evidence/'stage'))
    metadata={'images':images,'rollback':snapshots,'evidence':str(evidence)}
    (evidence/'rollback.json').write_text(json.dumps(metadata,indent=2))
    changed=False
    try:
        changed=True
        for role in NAMES:
            run('docker','tag',images[role],before[role]['Config']['Image'])
            run('docker','cp',str(target),NAMES[role]+':/app/'+name)
        (PROJECT/name).write_bytes(blob)
        old=before['admin']['Config']['Image'];assert main_before.count('image: '+old)==1
        main_path.write_text(main_before.replace('image: '+old,'image: '+images['admin']))
        old=before['reader']['Config']['Image'];assert reader_before.count('image: '+old)==1
        reader_path.write_text(reader_before.replace('image: '+old,'image: '+images['reader']))
        restart()
        assert config()==public,'Provider settings changed'
        for role in NAMES:
            actual=inspect(NAMES[role]);assert actual['Id']==before[role]['Id']
            assert actual['Config']==before[role]['Config'] and actual['HostConfig']==before[role]['HostConfig']
        result={**metadata,'status':'deployed','provider_settings_unchanged':True}
        (ROOT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    except BaseException:
        if changed:
            for role in NAMES:
                run('docker','tag',bases[role],before[role]['Config']['Image'])
                run('docker','cp',str(evidence/(role+'-wanfang.py')),NAMES[role]+':/app/'+name)
            (PROJECT/name).write_bytes(source_before);main_path.write_text(main_before);reader_path.write_text(reader_before);restart()
            print('Parser release rolled back',flush=True)
        raise


if __name__=='__main__':main()
