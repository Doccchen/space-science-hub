"""Server-only fixed-file release over a live snapshot; preserves unrelated web assets/TLS."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT = Path('/opt/space-news')
ROOT = Path('/root/news-agent-deployment-20261008')


def run(*args, capture=False):
    result = subprocess.run(args, cwd=PROJECT, text=True,
                            stdout=subprocess.PIPE if capture else None)
    if result.returncode:
        raise RuntimeError(f'{args[0]} operation failed ({result.returncode}); protected arguments omitted')
    return result.stdout


def get(path):
    with urllib.request.urlopen('http://127.0.0.1:18081' + path, timeout=10) as response:
        return json.load(response)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Server operator only')
    archive = ROOT / 'news-agent-release.tar.gz'
    expected = (ROOT / 'news-agent-release.tar.sha256').read_text().strip()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Release checksum mismatch')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = ROOT / stamp; evidence.mkdir(mode=0o700)
    stage = evidence / 'stage'; stage.mkdir()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 1000 or len({member.name for member in members}) != len(members):
            raise RuntimeError('Unexpected archive inventory')
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not member.isfile() or member.size > 10_000_000:
                raise RuntimeError('Unsafe release member')
            if path.parts[0] not in {'backend','web','tests','tools','requirements.txt','news-agent-manifest.json'}:
                raise RuntimeError('Unexpected release scope')
            destination = stage / member.name; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.extractfile(member).read())
    manifest = json.loads((stage / 'news-agent-manifest.json').read_text())
    for item in manifest['files']:
        if hashlib.sha256((stage / item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('File checksum mismatch')
    container = json.loads(run('docker','inspect','space-news-app-1',capture=True))[0]
    labels = container['Config'].get('Labels') or {}
    project, service = labels.get('com.docker.compose.project'), labels.get('com.docker.compose.service')
    if not project or service != 'app':
        raise RuntimeError('Unreviewed Compose service identity')
    matching = run('docker','ps','-aq','--filter','label=com.docker.compose.project='+project,
                   '--filter','label=com.docker.compose.service='+service,capture=True).splitlines()
    if len(matching) != 1 or not container['Id'].startswith(matching[0]):
        raise RuntimeError('Ambiguous Compose app labels; isolate operator containers before deployment')
    volume = next(mount['Name'] for mount in container['Mounts'] if mount['Destination'] == '/data')
    health_before, ai_before = get('/api/health'), get('/api/ai/status')
    for name, digest in manifest['existing_baselines'].items():
        content = subprocess.check_output(['docker','exec','space-news-app-1','cat','/app/' + name])
        if hashlib.sha256(content.replace(b'\r\n',b'\n')).hexdigest() not in {digest, hashlib.sha256((stage / name).read_bytes()).hexdigest()}:
            raise RuntimeError('Live file differs from reviewed baseline: ' + name)
    shutil.copy2(PROJECT / '.env', evidence / 'environment-before')
    shutil.copy2(PROJECT / 'compose.yaml', evidence / 'compose-before.yaml')
    override = PROJECT / 'compose.override.yaml'
    shutil.copy2(override, evidence / 'https-override-before.yaml')
    changes = []
    for entry in container['Config'].get('Env', []):
        name = entry.partition('=')[0]
        if re.search(r'API_KEY|SERVICE_KEY|ACCESS_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN',name) and not name.endswith(('_FILE','_PATH')):
            changes += ['--change','ENV ' + name + '=']
    snapshot = 'space-news-agent-before:' + stamp
    run('docker','commit',*changes,'space-news-app-1',snapshot)
    (evidence / 'snapshot-tag').write_text(snapshot + '\n')
    dockerfile = ('FROM ' + snapshot + '\nUSER 0\nCOPY requirements.txt /tmp/news-agent-requirements.txt\n'
                  'RUN python -m pip install --no-cache-dir --disable-pip-version-check '
                  '--index-url https://mirrors.aliyun.com/pypi/simple -r /tmp/news-agent-requirements.txt pytest\n'
                  'COPY backend /app/backend\nCOPY web /app/web\nCOPY tools /app/tools\nCOPY tests /app/tests\n'
                  'RUN python /app/tools/news_limits_admin_overlay.py --root /app --backend-only\n'
                  'COPY requirements.txt /app/requirements.txt\nUSER 10001:10001\n')
    (stage / 'Dockerfile').write_text(dockerfile)
    image = 'space-news-agent-release:' + stamp
    run('docker','build','--pull=false','-t',image,str(stage))
    run('docker','run','--rm','--tmpfs','/data:rw,uid=10001,gid=10001,mode=0700',
        '-e','COLLECT_ENABLED=0',image,'python','-m','pytest',
        'tests/test_news_agent.py','tests/test_ai.py','tests/test_reading.py','tests/test_publisher_fetch.py',
        'tests/test_admin.py','tests/test_auto_fulltext.py','tests/test_apod_policy.py',
        'tests/test_news_limits.py','tests/test_ai_management.py','-q')
    run('docker','run','--rm','--volumes-from','space-news-app-1',image,
        'python','-m','tools.news_agent_operator','bootstrap')
    run('docker','run','--rm','--volumes-from','space-news-app-1',
        '-e','NEWS_AGENT_USAGE_DB_PATH=/data/news-agent-usage.sqlite3',image,
        'python','-m','tools.migrate_news_usage')
    backup = ("import sqlite3; from pathlib import Path; from contextlib import closing; "
              f"target=Path('/data/news-agent-before-{stamp}'); target.mkdir(mode=0o700)\n"
              "for p in Path('/data').glob('*.sqlite3'):\n"
              " with closing(sqlite3.connect(str(p))) as origin,closing(sqlite3.connect(str(target/p.name))) as saved:\n"
              "  origin.backup(saved)\nprint('Online database backups complete')")
    run('docker','exec','space-news-app-1','python','-c',backup)
    changed = False
    try:
        changed = True
        # Patch app.environment only; TLS binding, admin, resource and provider settings remain intact.
        compose = (PROJECT / 'compose.yaml').read_text().replace('\r\n','\n')
        anchor = '      AI_TOKEN_RESERVATION: ${AI_TOKEN_RESERVATION:-20000}\n'
        if anchor not in compose:
            raise RuntimeError('Unreviewed Compose environment layout')
        additions = ('      NEWS_AGENT_ENABLED: ${NEWS_AGENT_ENABLED:-0}\n'
                     '      NEWS_CONTEXT_ENABLED: ${NEWS_CONTEXT_ENABLED:-1}\n'
                     '      NEWS_AGENT_DB_PATH: /data/news-agent.sqlite3\n'
                     '      NEWS_AGENT_CREDENTIALS_FILE: /data/news-agent-credentials.json\n'
                     '      NEWS_AGENT_APP_ID: ${NEWS_AGENT_APP_ID:-e366df4514cb4606b95821b9d03c387e}\n'
                     '      NEWS_AGENT_WORKSPACE_ID: ${NEWS_AGENT_WORKSPACE_ID:-llm-ep9bqc9mnw50k8e0}\n'
                     '      NEWS_AGENT_REGION: ${NEWS_AGENT_REGION:-beijing}\n'
                     '      NEWS_AGENT_CONFIG_VERSION: ${NEWS_AGENT_CONFIG_VERSION:-news-agent-v2}\n'
                     '      NEWS_MCP_ENABLED: ${NEWS_MCP_ENABLED:-0}\n'
                     '      NEWS_MCP_CONTEXT_VERIFIED: ${NEWS_MCP_CONTEXT_VERIFIED:-0}\n'
                     '      NEWS_MCP_PLUGIN_CODE: ${NEWS_MCP_PLUGIN_CODE:-}\n')
        if '      NEWS_AGENT_ENABLED:' not in compose:
            compose = compose.replace(anchor,anchor + additions,1)
        if '      NEWS_AGENT_USAGE_DB_PATH:' not in compose:
            compose = compose.replace(anchor,anchor+'      NEWS_AGENT_USAGE_DB_PATH: /data/news-agent-usage.sqlite3\n',1)
        (PROJECT / 'compose.yaml').write_text(compose)
        overrides = {'NEWS_AGENT_ENABLED':'0','NEWS_CONTEXT_ENABLED':'1','NEWS_MCP_ENABLED':'0',
                     'NEWS_MCP_CONTEXT_VERIFIED':'0','NEWS_AGENT_CONFIG_VERSION':'news-agent-v2'}
        env = (PROJECT / '.env').read_text().splitlines()
        env = [line for line in env if line.partition('=')[0].strip() not in overrides]
        (PROJECT / '.env').write_text('\n'.join(env + [f'{key}={value}' for key,value in overrides.items()]) + '\n')
        (PROJECT / '.env').chmod(0o600)
        run('docker','tag',image,'space-news-app')
        run('docker','compose','config','--quiet')
        run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','app')
        for _ in range(60):
            try:
                health_after = get('/api/health'); break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('Release failed startup')
        after = json.loads(run('docker','inspect','space-news-app-1',capture=True))[0]
        if next(mount['Name'] for mount in after['Mounts'] if mount['Destination']=='/data') != volume:
            raise RuntimeError('Persistent volume changed')
        if health_after['articles'] < health_before['articles'] or get('/api/ai/status') != ai_before:
            raise RuntimeError('Existing site regression')
        agent = get('/api/news/362/agent-status')
        if agent['enabled'] or agent['mcp_service_enabled'] or agent['mcp_enabled']:
            raise RuntimeError('Unsafe or unavailable bootstrap state')
        unchanged_code = ("import hashlib,json; from pathlib import Path; "
                          "print(json.dumps({str(p.relative_to('/app/web')):hashlib.sha256(p.read_bytes()).hexdigest() "
                          "for p in Path('/app/web').rglob('*') if p.is_file()}))")
        old_web = json.loads(run('docker','run','--rm',snapshot,'python','-c',unchanged_code,capture=True))
        new_web = json.loads(run('docker','exec','space-news-app-1','python','-c',unchanged_code,capture=True))
        intentional = {item['path'][4:] for item in manifest['files'] if item['path'].startswith('web/')}
        if any(new_web.get(name) != digest for name,digest in old_web.items() if name not in intentional):
            raise RuntimeError('Unrelated live frontend files changed')
        for item in manifest['files']:
            if item['path'].startswith(('backend/','web/','tools/')):
                live = subprocess.check_output(['docker','exec','space-news-app-1','cat','/app/' + item['path']])
                if hashlib.sha256(live).hexdigest() != item['sha256']:
                    raise RuntimeError('Release runtime file mismatch')
        result = {'status':'deployed','image':image,'snapshot':snapshot,'evidence':str(evidence),
                  'health':health_after,'public_generation_enabled':False,'mcp_bootstrap_enabled':False,
                  'unrelated_web_bytes_preserved':True,'model_calls':0}
        (evidence / 'result.json').write_text(json.dumps(result,indent=2)+'\n')
        (ROOT / 'latest-evidence-path').write_text(str(evidence)+'\n')
        print(json.dumps(result))
    except BaseException:
        if changed:
            shutil.copy2(evidence / 'environment-before',PROJECT / '.env')
            shutil.copy2(evidence / 'compose-before.yaml',PROJECT / 'compose.yaml')
            run('docker','tag',snapshot,'space-news-app')
            run('docker','compose','up','-d','--no-deps','--no-build','--pull','never','app')
        raise


if __name__ == '__main__':
    main()
