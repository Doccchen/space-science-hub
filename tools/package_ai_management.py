"""Allowlisted AI/admin update; never includes Compose, keys or runtime data."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ('backend/ai.py','backend/ai_config.py','backend/ai_runtime.py','backend/ai_admin.py',
         'backend/app.py','backend/admin_app.py','backend/management_store.py','backend/resource_admin.py','backend/resources.py',
         'admin_web/index.html','admin_web/admin.js','admin_web/admin.css','admin_web/resources.js','admin_web/ai-settings.js',
         'web/ai-ui.js','tools/ai_manage.py','tools/resources_manage.py','requirements.txt',
         'tests/test_ai_management.py','tests/test_ai.py', 'docs/deployment/AI设置后台部署-20261006.md')


def main():
    destination = ROOT/'artifacts/packages'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination/'space-ai-management-20261006.tar.gz'
    manifest = {'files':[]}
    with tarfile.open(archive,'w:gz') as bundle:
        for name in FILES:
            data = (ROOT/name).read_bytes().replace(b'\r\n',b'\n')
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o644
            bundle.addfile(member, io.BytesIO(data))
            manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
        data = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        member = tarfile.TarInfo('ai-management-manifest.json'); member.size = len(data); member.mode = 0o644
        bundle.addfile(member,io.BytesIO(data))
    with tarfile.open(archive,'r:gz') as bundle:
        assert set(bundle.getnames()) == set(FILES) | {'ai-management-manifest.json'}
        for row in manifest['files']:
            assert hashlib.sha256(bundle.extractfile(row['path']).read()).hexdigest() == row['sha256']
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('').with_suffix('.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'files':len(FILES),'bytes':archive.stat().st_size,'sha256':checksum},ensure_ascii=False))


if __name__ == '__main__': main()
