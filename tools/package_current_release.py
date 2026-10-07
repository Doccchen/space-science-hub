"""Build a complete runtime upgrade from committed Git bytes, without local data or secrets."""
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files={}
    paths=['backend','web','admin_web','content','tools','tests','Dockerfile','requirements.txt','compose.yaml']
    raw=subprocess.check_output(['git','archive','--format=tar',revision,*paths],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for item in archive.getmembers():
            if item.isdir():continue
            if not item.isfile():raise ValueError('Unexpected non-file: '+item.name)
            files[item.name]=archive.extractfile(item).read()
    forbidden={'.env','secrets','data','artifacts','.venv','.git'}
    assert all(not forbidden.intersection(Path(name).parts) and not name.endswith(('.pem','.sqlite3','.db')) for name in files)
    manifest={'revision':revision,'files':[{'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in sorted(files.items())]}
    files['release-manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    package=output/'space-unified-release-20261007.tar.gz'
    with tarfile.open(package,'w:gz') as archive:
        for name,data in sorted(files.items()):
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;archive.addfile(item,io.BytesIO(data))
    sha=hashlib.sha256(package.read_bytes()).hexdigest()
    (output/'space-unified-release-20261007.sha256').write_text(sha+'  '+package.name+'\n',encoding='ascii')
    (output/'space-unified-release-20261007.revision').write_text(revision+'\n',encoding='ascii')
    (output/'deploy_current_release.sh').write_bytes(files['tools/deploy_current_release.sh'])
    with tarfile.open(package) as archive:
        assert set(archive.getnames())==set(files)
        for name,data in files.items():assert archive.extractfile(name).read()==data
    print(json.dumps({'revision':revision,'archive':package.name,'files':len(manifest['files']),'bytes':package.stat().st_size,'sha256':sha}))


if __name__=='__main__':main()
