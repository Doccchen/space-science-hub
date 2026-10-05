"""Build a clean deployment archive; normalize text to LF for Linux."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    output = ROOT / 'artifacts/packages'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'space-resources-release.tar.gz'
    paths = []
    for directory in ('backend', 'web', 'content', 'tests', 'tools'):
        paths.extend(path for path in (ROOT/directory).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix != '.pyc')
    paths.extend(ROOT/name for name in ('Dockerfile','.dockerignore','compose.yaml','requirements.txt','.env.example','README.md'))
    paths.append(ROOT/'docs/deployment/资料下载部署步骤.md')
    excluded = {'preview_resources.py','prepare_resource_covers.py','draft_resource_metadata.py',
                'prepare_resource_release.py','prepare_resources.py','package_resources.py'}
    files = []
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(set(paths)):
            if path.name in excluded:
                continue
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            if path.suffix in ('.py','.sh','.json','.js','.css','.html','.md','.yaml','.txt') or path.name in ('Dockerfile','.dockerignore','.env.example'):
                data = data.replace(b'\r\n', b'\n')
            assert not path.name.endswith(('.pem','.pdf','.sqlite3')) and path.name != '.env'
            info = tarfile.TarInfo(relative)
            info.size, info.mode = len(data), 0o755 if path.suffix == '.sh' else 0o644
            tar.addfile(info, io.BytesIO(data))
            files.append({'path':relative,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    manifest = {'archive':archive.name,'archive_size':archive.stat().st_size,
                'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}
    (output/'space-resources-release.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in manifest.items() if key!='files'},ensure_ascii=False))


if __name__ == '__main__':
    main()
