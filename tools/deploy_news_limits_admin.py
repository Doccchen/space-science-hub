"""Overlay only news limits UI/routes on the live private admin image."""
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

PROJECT=Path('/opt/space-news');ROOT=Path('/root/news-agent-deployment-20261008')


def run(*args,capture=False):
    return subprocess.check_output(args,cwd=PROJECT,text=True) if capture else subprocess.run(args,cwd=PROJECT,check=True)


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');evidence=ROOT/('admin-news-limits-'+stamp);evidence.mkdir(mode=0o700)
    stage=evidence/'stage';(stage/'backend').mkdir(parents=True);(stage/'admin_web').mkdir()
    old=json.loads(run('docker','inspect','space-news-admin-1',capture=True))[0]
    labels=old['Config'].get('Labels') or {};project=labels.get('com.docker.compose.project')
    if not project or labels.get('com.docker.compose.service')!='admin':raise RuntimeError('Unreviewed admin identity')
    matching=run('docker','ps','-aq','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=admin',capture=True).splitlines()
    if len(matching)!=1 or not old['Id'].startswith(matching[0]):raise RuntimeError('Ambiguous admin Compose identity')
    for name in ('backend/admin_app.py','admin_web/index.html','admin_web/ai-settings.js','admin_web/resources.js'):
        run('docker','cp','space-news-admin-1:/app/'+name,str(stage/name))
    for name in ('news_limits.py','news_limits_admin.py'):
        shutil.copy2(ROOT/name,stage/'backend'/name)
    shutil.copy2(ROOT/'news-limits.js',stage/'admin_web/news-limits.js')
    run('python3',str(ROOT/'news_limits_admin_overlay.py'),'--root',str(stage))
    snapshot='space-news-admin-before-news-limits:'+stamp
    changes=[]
    for entry in old['Config'].get('Env',[]):
        name=entry.partition('=')[0]
        if any(part in name for part in ('SECRET','PASSWORD','API_KEY','SERVICE_KEY')) and not name.endswith(('_FILE','_PATH')):
            changes+=['--change','ENV '+name+'=']
    run('docker','commit',*changes,'space-news-admin-1',snapshot)
    (stage/'Dockerfile').write_text('FROM '+snapshot+'\nUSER 0\nCOPY backend /app/backend\nCOPY admin_web /app/admin_web\nUSER 10001:10001\n')
    image='space-news-admin-news-limits:'+stamp;run('docker','build','-t',image,str(stage))
    try:
        run('docker','tag',image,'space-news-admin')
        run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','admin')
        for _ in range(45):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=3) as reply:
                    if reply.status==200:break
            except Exception:time.sleep(1)
        else:raise RuntimeError('Admin startup failed')
        with urllib.request.urlopen('http://127.0.0.1:8090/news-limits.js',timeout=3) as reply:
            if hashlib.sha256(reply.read()).digest()!=hashlib.sha256((stage/'admin_web/news-limits.js').read_bytes()).digest():
                raise RuntimeError('Admin asset mismatch')
        try:
            urllib.request.urlopen('http://127.0.0.1:8090/api/news-agent-limits',timeout=3)
            raise RuntimeError('Unprotected admin route')
        except urllib.error.HTTPError as error:
            if error.code!=401:raise
        after=json.loads(run('docker','inspect','space-news-admin-1',capture=True))[0]
        if after['Mounts']!=old['Mounts']:raise RuntimeError('Admin mounts changed')
        result={'status':'deployed','image':image,'snapshot':snapshot,'evidence':str(evidence),'model_calls':0,'route_requires_login':True}
        (evidence/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    except BaseException:
        run('docker','tag',snapshot,'space-news-admin');run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','admin');raise


if __name__=='__main__':main()
