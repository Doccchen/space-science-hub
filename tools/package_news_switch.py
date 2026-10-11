"""Package only the news Agent switch files, with the reviewed git baselines."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('backend/app.py','backend/news_agent.py','backend/news_limits.py',
         'admin_web/news-limits.js','tests/test_news_agent.py','tests/test_news_limits.py')


def main():
    output = ROOT/'artifacts/news-switch-deployment'
    output.mkdir(parents=True,exist_ok=True)
    files = {name:(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in FILES}
    baselines = {}
    for name in FILES[:4]:
        data = subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}',
                                        'show','HEAD:'+name],cwd=ROOT)
        baselines[name] = hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
    archive_path = output/'release.tar.gz'
    with tarfile.open(archive_path,'w:gz') as archive:
        for name,data in files.items():
            item = tarfile.TarInfo(name)
            item.size,item.mode = len(data),0o644
            archive.addfile(item,io.BytesIO(data))
    manifest = {'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
                'baselines':baselines,'archive_sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    shutil.copy2(ROOT/'tools/deploy_news_switch.py',output/'deploy_news_switch.py')
    print(json.dumps({'directory':str(output),'sha256':manifest['archive_sha256']}))


if __name__ == '__main__':
    main()
