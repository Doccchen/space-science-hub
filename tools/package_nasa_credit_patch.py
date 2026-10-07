"""Small, byte-verified historical NASA attribution parser patch."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FILES=('backend/news_thumbnails.py','tests/test_news_thumbnails.py','docs/deployment/NASA历史配图署名修复-20261007.md')


def main():
    folder=ROOT/'artifacts/packages';folder.mkdir(parents=True,exist_ok=True)
    blobs={name:(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in FILES}
    manifest={'files':[{'path':name,'sha256':hashlib.sha256(data).hexdigest()} for name,data in blobs.items()]}
    blobs['nasa-credits-manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    archive=folder/'space-nasa-credits-20261007.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in blobs.items():
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644;tar.addfile(item,io.BytesIO(data))
    with tarfile.open(archive) as tar:
        assert set(tar.getnames())==set(blobs)
        for name,data in blobs.items():assert tar.extractfile(name).read()==data
    (folder/'space-nasa-credits-20261007.sha256').write_bytes((hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n').encode('ascii'))
    (folder/'upgrade_nasa_credits.sh').write_bytes((ROOT/'tools/upgrade_nasa_credits.sh').read_bytes().replace(b'\r\n',b'\n'))
    print('NASA credit patch and LF checksum/script generated:',archive.stat().st_size,'bytes')


if __name__=='__main__':main()
