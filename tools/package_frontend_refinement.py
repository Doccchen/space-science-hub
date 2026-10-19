"""Fixed-file frontend refinement release, preserving the downloaded live index."""
import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
try:
    from .build_styles import build, GROUPS
except ImportError:
    from build_styles import build, GROUPS

ROOT=Path(__file__).resolve().parents[1]
FILES=('backend/news_agent.py','tests/test_news_agent.py','tests/test_news_limits.py',
       'tools/build_styles.py','web/index.html','web/news-ui.js','web/news-agent-availability.js',
       'web/editorial.css','web/styles/base.css','web/styles/components.css','web/styles/pages.css','web/styles/README.md')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    baseline=parser.parse_args().baseline
    build()
    output=ROOT/'artifacts/frontend-refinement-deployment';output.mkdir(parents=True,exist_ok=True)
    git=['git','-c',f'safe.directory={ROOT.as_posix()}']
    baselines={}
    # Each style source must match the reviewed live source except the requested typography edit.
    for name in ['index.html','news-ui.js']+[n for group in GROUPS.values() for n in group]:
        data=(baseline/'web'/name).read_bytes()
        baselines['web/'+name]=hashlib.sha256(data).hexdigest()
        if name not in ('index.html','news-ui.js','editorial.css'):
            assert data.replace(b'\r\n',b'\n')==(ROOT/'web'/name).read_bytes().replace(b'\r\n',b'\n'),name
    old=subprocess.check_output(git+['show','HEAD:backend/news_agent.py'],cwd=ROOT)
    baselines['backend/news_agent.py']=hashlib.sha256(old.replace(b'\r\n',b'\n')).hexdigest()
    index=(baseline/'web/index.html').read_text(encoding='utf-8')
    index=re.sub(r'<link rel="stylesheet"[^>]*>','',index)
    entries=''.join(f'<link rel="stylesheet" href="/assets/styles/{name}.css?v=20261011">' for name in ('base','components','pages'))
    index=index.replace('</head>',entries+'</head>')
    index=index.replace('<script src="/assets/news-ui.js','<script src="/assets/news-agent-availability.js?v=20261011"></script><script src="/assets/news-ui.js')
    index=re.sub(r'(/assets/news-ui\.js)\?v=[^" ]+',r'\1?v=20261011-availability',index)
    files={name:(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in FILES}
    files['web/index.html']=index.encode()
    archive=output/'release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in files.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644
            tar.addfile(entry,io.BytesIO(data))
    manifest={'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
              'baselines':baselines,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    for name in ('deploy_frontend_refinement.py','deploy_news_switch.py'):
        shutil.copy2(ROOT/'tools'/name,output/name)
    print(json.dumps({'directory':str(output),'sha256':manifest['archive_sha256'],'files':len(files)}))


if __name__=='__main__':main()
