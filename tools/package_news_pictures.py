"""Allowlisted news-thumbnail release, including APOD exclusion; no private media/data."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FILES=('backend/news_thumbnails.py','backend/news_policy.py','backend/news.py','backend/app.py','backend/auto_fulltext.py',
       'backend/reading.py','backend/publisher_fetch.py','web/news-ui.js','web/news-state.js','web/quiet-ui.css','web/index.html',
       'tools/news_thumbnail_manage.py','tools/backup_review.py','tests/test_news_thumbnails.py','tests/test_apod_policy.py','tests/test_news.py',
       'docs/deployment/NASA与ESA新闻配图部署-20261007.md')


def main():
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    archive=output/'space-news-pictures-20261007.tar.gz';manifest={'files':[]}
    with tarfile.open(archive,'w:gz') as bundle:
        for name in FILES:
            data=(ROOT/name).read_bytes().replace(b'\r\n',b'\n')
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644
            bundle.addfile(entry,io.BytesIO(data));manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
        data=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        entry=tarfile.TarInfo('news-pictures-manifest.json');entry.size=len(data);entry.mode=0o644;bundle.addfile(entry,io.BytesIO(data))
    with tarfile.open(archive,'r:gz') as bundle:
        assert set(bundle.getnames())==set(FILES)|{'news-pictures-manifest.json'}
        for entry in manifest['files']:assert hashlib.sha256(bundle.extractfile(entry['path']).read()).hexdigest()==entry['sha256']
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/'space-news-pictures-20261007.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'files':len(FILES),'sha256':checksum},ensure_ascii=False))


if __name__=='__main__':main()
