"""Small APOD scope release; no runtime data, configuration or frontend changes."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FILES=('backend/news_policy.py','backend/news.py','backend/app.py','backend/auto_fulltext.py',
       'tests/test_apod_policy.py','tests/test_news.py','docs/deployment/APOD排除部署-20261007.md')


def main():
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    archive=output/'space-apod-exclusion-20261007.tar.gz'
    manifest={'files':[]}
    with tarfile.open(archive,'w:gz') as bundle:
        for name in FILES:
            data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
            member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o644
            bundle.addfile(member,io.BytesIO(data))
            manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
        data=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        member=tarfile.TarInfo('apod-release-manifest.json');member.size=len(data);member.mode=0o644
        bundle.addfile(member,io.BytesIO(data))
    with tarfile.open(archive,'r:gz') as bundle:
        assert set(bundle.getnames())==set(FILES)|{'apod-release-manifest.json'}
        for item in manifest['files']:
            assert hashlib.sha256(bundle.extractfile(item['path']).read()).hexdigest()==item['sha256']
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/'space-apod-exclusion-20261007.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'sha256':checksum,'files':len(FILES)},ensure_ascii=False))


if __name__=='__main__':main()
