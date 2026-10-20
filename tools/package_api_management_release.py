"""Package an explicit file allowlist; never includes environment files or API keys."""
import hashlib
import io
import json
import shutil
import tarfile
from tools.prepare_api_management_release import ROOT,OUT

READER=['reader/__init__.py','reader/app.py','reader/config.py','reader/discovery.py',
        'reader/wanfang.py','reader/sciencedirect.py','reader/provider_runtime.py']
GROUPS={
    'app':['web/research.html','web/research.css','web/research.js'],
    'admin':['backend/admin_app.py','backend/literature_admin.py','backend/literature_config.py',
             'admin_web/index.html','admin_web/admin.css','admin_web/admin.js','admin_web/ai-settings.js',
             'admin_web/api-settings.js']+[n for n in READER if n!='reader/app.py'],
    'reader':READER+['backend/literature_config.py'],
}


def main():
    state=json.loads((OUT/'preflight.json').read_text())
    files={};baselines={}
    for role,names in GROUPS.items():
        baselines[role]={}
        for name in names:
            path=OUT/'baseline'/role/name
            baselines[role][name]=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    with tarfile.open(OUT/'release.tar.gz','w:gz') as archive:
        for name in sorted({n for names in GROUPS.values() for n in names}):
            assert not name.startswith('.') and name.endswith(('.py','.html','.js','.css'))
            blob=(ROOT/name).read_bytes();files[name]=hashlib.sha256(blob).hexdigest()
            member=tarfile.TarInfo(name);member.size=len(blob);member.mode=0o644
            archive.addfile(member,io.BytesIO(blob))
    manifest={'groups':GROUPS,'files':files,'baselines':baselines,'containers':state['containers'],
              'config_hashes':state['config_hashes'],
              'archive_sha256':hashlib.sha256((OUT/'release.tar.gz').read_bytes()).hexdigest()}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    shutil.copy2(ROOT/'tools/deploy_api_management.py',OUT/'deploy_api_management.py')
    print(json.dumps({'files':len(files),'runtime_copies':sum(map(len,GROUPS.values())),
                      'bytes':(OUT/'release.tar.gz').stat().st_size,'contains_keys':False}))


if __name__=='__main__':main()
