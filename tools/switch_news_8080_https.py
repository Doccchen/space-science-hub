"""Authorized server-only TLS switch, preserving live hot-updated app bytes."""
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path('/opt/space-news')
STAGE = Path('/root/news-mcp-https-20261008')
SITE = Path('/etc/nginx/sites-available/space-news-mcp')
OVERRIDE = PROJECT / 'compose.override.yaml'


def run(*args, capture=False):
    try:
        return subprocess.run(args, cwd=PROJECT, check=True, text=True,
                              stdout=subprocess.PIPE if capture else None).stdout
    except subprocess.CalledProcessError as error:
        # Arguments may include image environment values. Never print those on failure.
        raise RuntimeError(f'{args[0]} operation failed with exit {error.returncode}') from None


def inspect():
    return json.loads(run('docker', 'inspect', 'space-news-app-1', capture=True))[0]


def web_digest():
    code = ("import hashlib,json; from pathlib import Path; "
            "print(json.dumps({str(p.relative_to('/app/web')):hashlib.sha256(p.read_bytes()).hexdigest() "
            "for p in Path('/app/web').rglob('*') if p.is_file()},sort_keys=True))")
    return json.loads(run('docker', 'exec', 'space-news-app-1', 'python', '-c', code, capture=True))


def get(path, port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
        return json.load(response)


def update_env():
    path = PROJECT / '.env'
    lines = path.read_text().splitlines()
    updates = {'BIND_ADDRESS': '127.0.0.1', 'WEB_PORT': '18081', 'AI_COOKIE_SECURE': '1'}
    lines = [line for line in lines if line.partition('=')[0].strip() not in updates]
    path.write_text('\n'.join(lines + [f'{name}={value}' for name, value in updates.items()]) + '\n')
    path.chmod(0o600)


def main():
    if os.geteuid() != 0 or OVERRIDE.exists() or not SITE.is_file():
        raise RuntimeError('Expected fresh authorized switch with no Compose override')
    if any((PROJECT / name).exists() for name in ('compose.override.yml', 'docker-compose.override.yml', 'docker-compose.override.yaml')):
        raise RuntimeError('Existing override requires manual review')
    with socket.socket() as test:
        test.bind(('127.0.0.1', 18081))
    current = inspect()
    image_ref = current['Config']['Image']
    if image_ref not in {'space-news-app', 'space-news-app:latest'}:
        raise RuntimeError('Unexpected runtime image reference')
    gateways = {network['Gateway'] for network in current['NetworkSettings']['Networks'].values()}
    if len(gateways) != 1:
        raise RuntimeError('Expected one reviewed app network')
    gateway = str(ipaddress.ip_address(gateways.pop()))
    health_before, status_before, web_before = get('/api/health', 8080), get('/api/ai/status', 8080), web_digest()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = STAGE / ('website-8080-' + stamp)
    evidence.mkdir(mode=0o700)
    shutil.copy2(PROJECT / '.env', evidence / 'environment-before')
    shutil.copy2(PROJECT / 'compose.yaml', evidence / 'compose-before.yaml')
    shutil.copy2(SITE, evidence / 'nginx-before.conf')
    template = STAGE / 'news-site-ip-8080-https.conf'
    if not template.is_file():
        raise RuntimeError('TLS template missing')

    # Back up each SQLite DB with SQLite's online backup API; never copy a live WAL main file alone.
    backup_code = ("import sqlite3; from pathlib import Path; from contextlib import closing; "
                   f"target=Path('/data/https-before-{stamp}'); target.mkdir(mode=0o700); "
                   "files=list(Path('/data').glob('*.sqlite3')); "
                   "\ndef backup(p,target):\n"
                   " with closing(sqlite3.connect(str(p))) as origin, closing(sqlite3.connect(str(target/p.name))) as dest:\n"
                   "  origin.backup(dest)\n"
                   "for p in files: backup(p,target)\n"
                   "print('Consistent SQLite backups:',len(files))")
    run('docker', 'exec', 'space-news-app-1', 'python', '-c', backup_code)
    snapshot_tag = 'space-news-https-before:' + stamp
    changes = []
    for entry in current['Config'].get('Env', []):
        name = entry.partition('=')[0]
        if re.search(r'API_KEY|SERVICE_KEY|ACCESS_KEY|SECRET|PASSWORD|AUTH_TOKEN|ACCESS_TOKEN', name) and not name.endswith(('_FILE', '_PATH')):
            changes += ['--change', f'ENV {name}=']
    committed = subprocess.run(['docker', 'commit', *changes, 'space-news-app-1', snapshot_tag],
                               cwd=PROJECT, text=True, capture_output=True)
    if committed.returncode:
        # A running snapshot can remain valid even when old content-store blobs were pruned.
        if 'content digest' not in committed.stderr or 'not found' not in committed.stderr:
            raise RuntimeError('Docker commit failed; existing service left unchanged')
        if shutil.disk_usage(evidence).free < 2_000_000_000:
            raise RuntimeError('Insufficient space for filesystem snapshot')
        exported = evidence / 'app-filesystem-before.tar'
        run('docker', 'export', '--output', str(exported), 'space-news-app-1')
        # Compose restores provider/runtime settings from its existing protected config.
        # Only base Python defaults are included in imported image metadata, never keys.
        defaults = {'PATH', 'LANG', 'PYTHON_VERSION', 'PYTHON_SHA256',
                    'PYTHONDONTWRITEBYTECODE', 'PYTHONUNBUFFERED', 'NEWS_DB_PATH'}
        import_changes = []
        for entry in current['Config'].get('Env', []):
            name, _, value = entry.partition('=')
            if name in defaults:
                import_changes += ['--change', f'ENV {name}={json.dumps(value)}']
        for name, directive in [('User', 'USER'), ('WorkingDir', 'WORKDIR')]:
            value = current['Config'].get(name)
            if value:
                import_changes += ['--change', f'{directive} {value}']
        for name, directive in [('Entrypoint', 'ENTRYPOINT'), ('Cmd', 'CMD')]:
            value = current['Config'].get(name)
            if value:
                import_changes += ['--change', f'{directive} {json.dumps(value)}']
        run('docker', 'import', *import_changes, str(exported), snapshot_tag)
        print('Reconstructed runtime snapshot from exported filesystem; no application changes')
    snapshot_id = run('docker', 'image', 'inspect', snapshot_tag, '--format', '{{.Id}}', capture=True).strip()
    metadata = {'original_container': current['Id'], 'original_image': current['Image'],
                'snapshot_image': snapshot_id, 'snapshot_tag': snapshot_tag, 'gateway': gateway,
                'health_before': health_before, 'web_before': web_before}
    (evidence / 'state.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (STAGE / 'latest-website-evidence-path').write_text(str(evidence) + '\n')
    changed = False
    try:
        changed = True
        run('docker', 'tag', snapshot_tag, image_ref)
        update_env()
        OVERRIDE.write_text('# HTTPS trusted host proxy; managed by switch_news_8080_https.py\n'
                            'services:\n  app:\n    environment:\n'
                            f'      FORWARDED_ALLOW_IPS: "127.0.0.1,{gateway}"\n')
        OVERRIDE.chmod(0o600)
        shutil.copy2(template, SITE)
        run('nginx', '-t')
        run('docker', 'compose', 'config', '--quiet')
        run('docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'app')
        for _ in range(45):
            try:
                health_after = get('/api/health', 18081)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('Private upstream failed startup')
        if health_after['articles'] < health_before['articles'] or web_digest() != web_before:
            raise RuntimeError('Data count or live web bytes changed unexpectedly')
        if get('/api/ai/status', 18081) != status_before:
            raise RuntimeError('AI public status unexpectedly changed')
        run('systemctl', 'reload', 'nginx')
        print(json.dumps({'status': 'switched', 'evidence': str(evidence), 'health': health_after,
                          'live_web_bytes_preserved': True, 'private_port': 18081}))
    except BaseException:
        if changed:
            shutil.copy2(evidence / 'nginx-before.conf', SITE)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            shutil.copy2(evidence / 'environment-before', PROJECT / '.env')
            if OVERRIDE.is_file():
                OVERRIDE.unlink()  # Only the file created by this fresh switch.
            run('docker', 'tag', snapshot_tag, image_ref)
            run('docker', 'compose', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'app')
        raise


if __name__ == '__main__':
    main()
