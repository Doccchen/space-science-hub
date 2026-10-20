"""Server-side static-only release with baseline checks and three-service rollback."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from deploy_news_switch import settings_state

PROJECT = Path('/opt/space-news')
ROOT = Path(__file__).resolve().parent
CONTAINERS = {'app': 'space-news-app-1', 'admin': 'space-news-admin-1', 'reader': 'space-news-paper-search'}
ROOTS = {'app': ('backend', 'web', 'admin_web', 'tests'), 'admin': ('backend', 'admin_web'), 'reader': ('reader', 'reader_web')}


def run(*args):
    return subprocess.check_output(args, cwd=PROJECT, text=True)


def inspect(service):
    return json.loads(run('docker', 'inspect', CONTAINERS[service]))[0]


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def hashes(service, image=None):
    code = "from pathlib import Path;import hashlib,json;print(json.dumps({str(p.relative_to('/app')):hashlib.sha256(p.read_bytes()).hexdigest() for r in " + repr(ROOTS[service]) + " for p in (Path('/app')/r).rglob('*') if p.is_file() and '__pycache__' not in p.parts}))"
    prefix = ['docker', 'run', '--rm', '--network', 'none', image] if image else ['docker', 'exec', CONTAINERS[service]]
    return json.loads(run(*prefix, 'python', '-c', code))


def config_hashes():
    return {name: digest((PROJECT / name).read_bytes()) for name in ('compose.yaml', 'compose.paper-search.yaml', '.env', '.env.reader')}


def get(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def main():
    assert os.geteuid() == 0, 'Server operator only'
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert digest((ROOT / 'release.tar.gz').read_bytes()) == manifest['archive_sha256']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = ROOT / stamp
    evidence.mkdir(mode=0o700)
    stage = evidence / 'stage'
    stage.mkdir()
    with tarfile.open(ROOT / 'release.tar.gz') as archive:
        members = archive.getmembers()
        assert len(members) == len(manifest['files']) and {m.name for m in members} == set(manifest['files'])
        for member in members:
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            blob = archive.extractfile(member).read()
            assert digest(blob) == manifest['files'][member.name]
            target = stage / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            target.chmod(0o644)

    groups = manifest['groups']
    before = {s: inspect(s) for s in groups}
    original = {s: hashes(s) for s in groups}
    settings = settings_state()
    assert not any(v['pending'] for v in settings['ledgers'].values()), 'Pending model requests'
    config = config_hashes()
    assert config == manifest['config_hashes'], 'Server configuration changed since preflight'
    ai = json.loads(get('http://127.0.0.1:18081/api/ai/status'))
    articles = json.loads(get('http://127.0.0.1:18081/api/health'))['articles']
    old_files, old_source, bases, images, rollback = {}, {}, {}, {}, {}
    for service, names in groups.items():
        old = before[service]
        assert old['Id'] == manifest['containers'][service], 'Container changed since preflight: ' + service
        assert old['State']['Health']['Status'] == 'healthy'
        for name in names:
            expected = manifest['baselines'][service][name]
            assert original[service].get(name) == expected, 'Live file changed: ' + service + '/' + name
            saved = evidence / 'runtime' / service / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            if expected is not None:
                run('docker', 'cp', old['Id'] + ':/app/' + name, str(saved))
                assert digest(saved.read_bytes()) == expected
                old_files[service, name] = saved
            else:
                old_files[service, name] = None
        base = json.loads(run('docker', 'image', 'inspect', old['Config']['Image']))[0]['Id']
        assert hashes(service, base) == original[service], 'Published image differs from live files: ' + service
        bases[service] = base
        rollback[service] = 'space-news-before-design-audit-' + service + ':' + stamp
        images[service] = 'space-news-design-audit-' + service + ':' + stamp
        run('docker', 'tag', base, rollback[service])
        dockerfile = stage / ('Dockerfile.' + service)
        dockerfile.write_text('FROM ' + base + '\nUSER 0\n' + ''.join('COPY ' + n + ' /app/' + n + '\n' for n in names) + 'USER ' + (old['Config'].get('User') or '0') + '\n')
        run('docker', 'build', '--pull=false', '-f', str(dockerfile), '-t', images[service], str(stage))
    for name in manifest['files']:
        target = PROJECT / name
        old_source[name] = target.read_bytes() if target.is_file() else None
        if old_source[name] is not None:
            saved = evidence / 'source' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(old_source[name])
    run('docker', 'run', '--rm', '--network', 'none', images['app'], 'python', 'tools/build_styles.py', '--check')
    metadata = {'images': images, 'rollback': rollback, 'tags': {s: d['Config']['Image'] for s, d in before.items()},
                'containers': {s: d['Id'] for s, d in before.items()}, 'evidence': str(evidence)}
    (evidence / 'rollback.json').write_text(json.dumps(metadata, indent=2))
    changed = False
    try:
        changed = True
        for service, names in groups.items():
            run('docker', 'tag', images[service], before[service]['Config']['Image'])
            for name in sorted(names, key=lambda n: n.endswith('.html')):
                run('docker', 'cp', str(stage / name), before[service]['Id'] + ':/app/' + name)
        for name in manifest['files']:
            target = PROJECT / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / name, target)
        for service, names in groups.items():
            current = inspect(service)
            assert current['Id'] == before[service]['Id']
            assert current['Config'] == before[service]['Config'] and current['HostConfig'] == before[service]['HostConfig']
            assert current['State']['Health']['Status'] == 'healthy'
            actual = hashes(service)
            assert all(actual.get(n) == h for n, h in original[service].items() if n not in names), 'Unrelated file changed'
            assert all(actual[n] == manifest['files'][n] for n in names), 'Released bytes differ'
            assert hashes(service, images[service]) == actual, 'Published/live image mismatch'
        assert settings_state() == settings and config_hashes() == config, 'Settings/configuration changed'
        assert json.loads(get('http://127.0.0.1:18081/api/ai/status')) == ai
        assert json.loads(get('http://127.0.0.1:18081/api/health'))['articles'] >= articles
        checked = {}
        for name in manifest['files']:
            if name.startswith('web/'):
                url = 'https://8.137.164.100:8080' + ('/' if name == 'web/index.html' else '/assets/' + name[4:])
            elif name.startswith('reader_web/'):
                url = 'https://8.137.164.100:8080' + ('/reader/' if name == 'reader_web/index.html' else '/reader-assets/' + name[11:])
            elif name.startswith('admin_web/'):
                url = 'http://127.0.0.1:8090/' + ('' if name == 'admin_web/index.html' else name[10:])
            else:
                continue
            assert digest(get(url)) == manifest['files'][name], 'Served bytes differ: ' + name
            checked[name] = manifest['files'][name]
        assert json.loads(get('https://8.137.164.100:8080/api/reader/health'))['service'] == 'paper-search'
        result = {**metadata, 'status': 'deployed', 'static_urls_checked': len(checked), 'settings_unchanged': True,
                  'containers_restarted': False, 'articles': json.loads(get('http://127.0.0.1:18081/api/health'))['articles']}
        (ROOT / 'result.json').write_text(json.dumps(result, indent=2))
        (evidence / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    except BaseException:
        if changed:
            for service, names in groups.items():
                run('docker', 'tag', bases[service], before[service]['Config']['Image'])
                for name in names:
                    saved = old_files[service, name]
                    if saved:
                        run('docker', 'cp', str(saved), before[service]['Id'] + ':/app/' + name)
                    else:
                        run('docker', 'exec', '-u', '0', before[service]['Id'], 'python', '-c', 'from pathlib import Path;Path(' + repr('/app/' + name) + ').unlink(missing_ok=True)')
            for name, blob in old_source.items():
                target = PROJECT / name
                if blob is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(blob)
            print('Release rolled back; protected evidence: ' + str(evidence), flush=True)
        raise


if __name__ == '__main__':
    main()
