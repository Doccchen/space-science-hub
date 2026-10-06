"""Prepare an AI delta release; no keys, databases, catalogs or preview fixtures."""
import hashlib
import io
import json
import tarfile
from pathlib import Path
from tools.install_ai_release import FILES

ROOT=Path(__file__).resolve().parent.parent


def main():
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    blobs={name:(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in FILES}
    manifest={'release':'space-ai-20261006','files':[
        {'path':name,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)} for name,data in blobs.items()]}
    blobs['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    archive=output/'space-ai-release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in blobs.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644;tar.addfile(entry,io.BytesIO(data))
    for name in ('configure_ai.py','install_ai_release.py','upgrade_ai.sh'):
        (output/name).write_bytes((ROOT/'tools'/name).read_bytes().replace(b'\r\n',b'\n'))
    (output/'space-ai-release.manifest.json').write_bytes(blobs['manifest.json'])
    print(json.dumps({'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
