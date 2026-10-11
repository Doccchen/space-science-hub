"""Package only the approved private admin layout and static logo route."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ('admin_web/index.html', 'admin_web/admin.css', 'admin_web/admin.js',
         'admin_web/brand.svg', 'backend/admin_app.py')

def main():
    output = ROOT/'artifacts/packages'
    output.mkdir(parents=True, exist_ok=True)
    blobs = {name:(ROOT/name).read_bytes().replace(b'\r\n', b'\n') for name in FILES}
    route = b"@app.get('/brand.svg')\ndef brand():\n    return FileResponse(STATIC/'brand.svg', media_type='image/svg+xml')\n\n\n"
    assert blobs['backend/admin_app.py'].count(route) == 1
    baseline = blobs['backend/admin_app.py'].replace(route, b'')
    manifest = {'release':'admin-layout-20261008', 'admin_baseline_sha256':hashlib.sha256(baseline).hexdigest(),
                'files':[{'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in blobs.items()]}
    blobs['admin-layout-manifest.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    archive = output/'space-admin-layout-20261008.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for name,data in blobs.items():
            item = tarfile.TarInfo(name); item.size=len(data); item.mode=0o644
            bundle.addfile(item,io.BytesIO(data))
    (output/'space-admin-layout-20261008.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n',encoding='ascii')
    print(archive.name, archive.stat().st_size)

if __name__ == '__main__':
    main()
