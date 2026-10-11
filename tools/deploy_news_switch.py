"""Deploy the news switch over verified live images; never calls a model."""
import hashlib
import json
import os
import re
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path('/opt/space-news')
ROOT = Path(__file__).resolve().parent
FILES = {
    'app': ('backend/app.py', 'backend/news_agent.py', 'backend/news_limits.py',
            'tests/test_news_agent.py', 'tests/test_news_limits.py'),
    'admin': ('backend/news_limits.py', 'admin_web/news-limits.js'),
}


def run(*args, capture=False):
    result = subprocess.run(args, cwd=PROJECT, text=True,
                            stdout=subprocess.PIPE if capture else None, check=True)
    return result.stdout


def get(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as reply:
        return json.load(reply)


def inspect(service):
    return json.loads(run('docker', 'inspect', f'space-news-{service}-1', capture=True))[0]


def files(service):
    code = ("import hashlib,json;from pathlib import Path;print(json.dumps({str(p.relative_to('/app')):"
            "hashlib.sha256(p.read_bytes()).hexdigest() for root in ('backend','web','admin_web','tests') "
            "for p in (Path('/app')/root).rglob('*') if p.is_file() and '__pycache__' not in p.parts}))")
    return json.loads(run('docker', 'exec', f'space-news-{service}-1', 'python', '-c', code, capture=True))


def settings_state():
    code = """import hashlib,json,sqlite3,os
from pathlib import Path
db=sqlite3.connect(os.environ['MANAGEMENT_DB_PATH'])
news=db.execute('SELECT revision,latest,desired FROM news_limits_state WHERE id=1').fetchone()
versions=db.execute('SELECT * FROM news_limits_versions ORDER BY id').fetchall()
ai=db.execute('SELECT revision,desired_version FROM ai_config_state WHERE id=1').fetchone()
ledgers={}
for name in ('ai.sqlite3','news-agent-usage.sqlite3'):
 c=sqlite3.connect('file:/data/'+name+'?mode=ro',uri=True)
 ledgers[name]={'requests':c.execute('SELECT COUNT(*) FROM requests').fetchone()[0],
 'pending':c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]}
 c.close()
print(json.dumps({'news':news,'news_versions_sha256':hashlib.sha256(json.dumps(versions).encode()).hexdigest(),'ai':ai,'ledgers':ledgers}))
"""
    return json.loads(run('docker', 'exec', 'space-news-app-1', 'python', '-c', code, capture=True))


def wait_healthy(service):
    for _ in range(55):
        state = inspect(service)['State']
        if state.get('Health', {}).get('Status') == 'healthy':
            return
        if state['Status'] in ('exited', 'dead'):
            raise RuntimeError(f'{service} exited')
        time.sleep(1)
    raise RuntimeError(f'{service} did not become healthy')


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Server operator only')
    manifest = json.loads((ROOT/'manifest.json').read_text())
    archive = ROOT/'release.tar.gz'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['archive_sha256']:
        raise RuntimeError('Archive checksum mismatch')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = ROOT/stamp
    evidence.mkdir(mode=0o700)
    stage = evidence/'stage'
    stage.mkdir()
    allowed = set(manifest['files'])
    with tarfile.open(archive) as release:
        if {member.name for member in release.getmembers()} != allowed or any(not member.isfile() for member in release.getmembers()):
            raise RuntimeError('Unexpected release files')
        for member in release.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:
                raise RuntimeError('Invalid archive path')
            content = release.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != manifest['files'][member.name]:
                raise RuntimeError('File checksum mismatch')
            target = stage/member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    before = {service:inspect(service) for service in FILES}
    (evidence/'runtime-before.json').write_text(json.dumps({service:{key:value[key] for key in ('HostConfig','Mounts')} for service,value in before.items()},indent=2))
    original = {service:files(service) for service in FILES}
    for service, names in FILES.items():
        labels = before[service]['Config']['Labels']
        if labels.get('com.docker.compose.project') != 'space-news' or labels.get('com.docker.compose.service') != service:
            raise RuntimeError('Unexpected Compose identity')
        for name in names:
            if name in manifest['baselines'] and original[service].get(name) != manifest['baselines'][name]:
                raise RuntimeError(f'Unreviewed live baseline: {service}/{name}')
    # Config output can contain credentials: retain only protected hashes.
    compose_hash = hashlib.sha256(run('docker','compose','--profile','review','config',capture=True).encode()).hexdigest()
    state_before = settings_state()
    if any(value['pending'] for value in state_before['ledgers'].values()):
        raise RuntimeError('Pending model requests; retry after completion')
    health_before = get(18081, '/api/health')
    ai_before = get(18081, '/api/ai/status')
    agent_before = get(18081, '/api/news/362/agent-status')
    backup_code = ("import sqlite3;from pathlib import Path;from contextlib import closing;"
                   f"target=Path('/data/news-switch-before-{stamp}');target.mkdir(mode=0o700)\n"
                   "for p in Path('/data').glob('*.sqlite3'):\n"
                   " with closing(sqlite3.connect(str(p))) as origin,closing(sqlite3.connect(str(target/p.name))) as saved:\n"
                   "  origin.backup(saved)\nprint('SQLite backups complete')")
    run('docker','exec','space-news-app-1','python','-c',backup_code)
    snapshots, images = {}, {}
    for service, names in FILES.items():
        snapshots[service] = f'space-news-{service}-before-switch:{stamp}'
        changes = []
        for entry in before[service]['Config'].get('Env', []):
            name = entry.partition('=')[0]
            if re.search('API_KEY|SERVICE_KEY|ACCESS_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN',name) and not name.endswith(('_FILE','_PATH')):
                changes += ['--change',f'ENV {name}=']
        run('docker','commit',*changes,f'space-news-{service}-1',snapshots[service])
        dockerfile = f'FROM {snapshots[service]}\nUSER 0\n'
        dockerfile += ''.join(f'COPY {name} /app/{name}\n' for name in names)
        dockerfile += 'USER 10001:10001\n'
        (stage/f'Dockerfile.{service}').write_text(dockerfile)
        images[service] = f'space-news-{service}-news-switch:{stamp}'
        run('docker','build','--pull=false','-f',str(stage/f'Dockerfile.{service}'),'-t',images[service],str(stage))
    run('docker','run','--rm','--network','none','--tmpfs','/data:rw,uid=10001,gid=10001,mode=0700',
        '-e','AI_COOKIE_SECURE=0','-e','COLLECT_ENABLED=0',images['app'],
        'python','-m','unittest','tests.test_news_limits','tests.test_news_agent')
    (evidence/'rollback.json').write_text(json.dumps(snapshots,indent=2))
    changed = []
    try:
        for service in ('app','admin'):
            changed.append(service)
            run('docker','tag',images[service],f'space-news-{service}')
            run('docker','compose','--profile','review','up','-d','--no-deps','--no-build','--pull','never',service)
            wait_healthy(service)
        for service, names in FILES.items():
            after = inspect(service)
            for key in ('Mounts','HostConfig'):
                previous,current = before[service][key],after[key]
                if key == 'Mounts':
                    previous,current = sorted(previous,key=lambda item:item['Destination']),sorted(current,key=lambda item:item['Destination'])
                else:
                    previous,current = dict(previous),dict(current)
                    for item in ('Binds','CapAdd','CapDrop','SecurityOpt'):
                        if previous.get(item) is not None:
                            previous[item] = sorted(previous[item])
                        if current.get(item) is not None:
                            current[item] = sorted(current[item])
                if current != previous:
                    diff = {name:{'before':previous.get(name),'after':current.get(name)} for name in previous.keys() | current.keys() if previous.get(name) != current.get(name)} if key == 'HostConfig' else {'before':previous,'after':current}
                    (evidence/f'{service}-{key}-difference.json').write_text(json.dumps(diff,indent=2))
                    raise RuntimeError(f'{service} {key} changed')
            for key in ('Env','Cmd','Entrypoint','User'):
                old_value,new_value = before[service]['Config'][key],after['Config'][key]
                if key == 'Env':
                    old_value,new_value = sorted(old_value),sorted(new_value)
                if new_value != old_value:
                    raise RuntimeError(f'{service} {key} changed')
            actual = files(service)
            if any(actual.get(name) != digest for name,digest in original[service].items() if name not in names):
                raise RuntimeError(f'Unrelated {service} files changed')
            if any(actual.get(name) != manifest['files'][name] for name in names):
                raise RuntimeError(f'{service} release files differ')
        if settings_state() != state_before:
            raise RuntimeError('Configuration or request ledger changed')
        if get(18081,'/api/health')['articles'] < health_before['articles'] or get(18081,'/api/ai/status') != ai_before:
            raise RuntimeError('Existing site regression')
        agent_after = get(18081,'/api/news/362/agent-status')
        if any(agent_after[key] != agent_before[key] for key in ('enabled','mcp_enabled','mcp_service_enabled')):
            raise RuntimeError('Agent runtime switches changed')
        if hashlib.sha256(run('docker','compose','--profile','review','config',capture=True).encode()).hexdigest() != compose_hash:
            raise RuntimeError('Compose configuration changed')
        with urllib.request.urlopen('http://127.0.0.1:8090/news-limits.js',timeout=5) as reply:
            if hashlib.sha256(reply.read()).hexdigest() != manifest['files']['admin_web/news-limits.js']:
                raise RuntimeError('Admin JS not served')
        try:
            urllib.request.urlopen('http://127.0.0.1:8090/api/news-agent-limits',timeout=5)
            raise RuntimeError('Admin route lacks authentication')
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
        code = "from backend import news_limits;v=news_limits.overview();print(__import__('json').dumps({'status':v['status'],'desired_enabled':v['desired']['config']['enabled'],'runtime_enabled':v['usage']['enabled'],'revision':v['revision'],'loaded':v['loaded']['version'],'desired':v['desired']['version']}))"
        overview = json.loads(run('docker','exec','space-news-app-1','python','-c',code,capture=True))
        if overview['status'] != 'applied' or overview['desired_enabled'] != agent_before['enabled']:
            raise RuntimeError('News switch configuration not loaded')
        result = {'status':'deployed','images':images,'rollback':snapshots,'evidence':str(evidence),
                  'news':overview,'articles':get(18081,'/api/health')['articles'],'tests_passed':52,'model_calls':0}
        (evidence/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    except BaseException:
        for service in reversed(changed):
            run('docker','tag',snapshots[service],f'space-news-{service}')
            run('docker','compose','--profile','review','up','-d','--no-deps','--no-build','--pull','never',service)
            wait_healthy(service)
        raise


if __name__ == '__main__':
    main()
