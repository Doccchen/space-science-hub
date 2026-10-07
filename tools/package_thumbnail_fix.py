"""Targeted fix for the real NASA article scopes, media wrapper and image-library CDN."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FILES=('backend/publisher_fetch.py','backend/news_thumbnails.py','tools/news_thumbnail_manage.py',
       'tests/test_news_thumbnails.py','docs/deployment/新闻配图首轮采集修复-20261007.md')


def main():
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    archive=output/'space-thumbnail-fix-20261007.tar.gz';manifest={'files':[]}
    with tarfile.open(archive,'w:gz') as tar:
        for name in FILES:
            data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
            member=tarfile.TarInfo(name);member.mode=0o644;member.size=len(data);tar.addfile(member,io.BytesIO(data))
            manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
        data=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        member=tarfile.TarInfo('thumbnail-fix-manifest.json');member.mode=0o644;member.size=len(data);tar.addfile(member,io.BytesIO(data))
    with tarfile.open(archive,'r:gz') as tar:
        assert set(tar.getnames())==set(FILES)|{'thumbnail-fix-manifest.json'}
        for entry in manifest['files']:assert hashlib.sha256(tar.extractfile(entry['path']).read()).hexdigest()==entry['sha256']
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/'space-thumbnail-fix-20261007.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'sha256':digest},ensure_ascii=False))


if __name__=='__main__':main()
