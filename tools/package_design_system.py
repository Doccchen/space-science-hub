"""Package shared UI rules against a downloaded live frontend baseline."""
import argparse
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ['design-system.css', 'news-ui.js', 'ai-ui.js', 'resource-navigation.html', 'index.html']


def patch_index(text):
    assert 'design-system.css' not in text, 'Baseline already contains this release'
    text = text.replace('</head>', '<link rel="stylesheet" href="/assets/design-system.css?v=20261009-m3"></head>')
    for name in ['ai-ui.js', 'news-ui.js']:
        text, count = re.subn(r'(/assets/' + re.escape(name) + r')\?v=[^" ]+', r'\1?v=20261009-m3', text)
        assert count == 1, name
    text, count = re.subn(r'(<textarea id="ai-question"[^>]*)(>)', r'\1 aria-describedby="ai-input-hint ai-feedback"\2', text)
    assert count == 1
    hint = '<p id="ai-input-hint" class="ai-input-hint">输入问题后发送，Ctrl / ⌘ + Enter 也可提交。</p>'
    assert text.count('<div class="ai-compose-actions">') == 1
    return text.replace('<div class="ai-compose-actions">', hint + '<div class="ai-compose-actions">')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, default=ROOT / 'artifacts',
                        help='Directory containing the four freshly downloaded live HTML/JS files')
    baseline = parser.parse_args().baseline
    output = ROOT / 'artifacts/packages'
    output.mkdir(parents=True, exist_ok=True)
    blobs = {'web/' + name: (ROOT / 'web' / name).read_bytes() for name in NAMES}
    blobs['web/index.html'] = patch_index((baseline / 'index.html').read_text(encoding='utf-8')).encode()
    manifest = {'release': 'zhihang-design-system-20261009', 'files': [
        {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in blobs.items()]}
    blobs['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    archive = output / 'design-system-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in blobs.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = 0o644
            tar.addfile(entry, io.BytesIO(data))
    script = (ROOT / 'tools/upgrade_glass.sh').read_text(encoding='utf-8').replace('\r\n', '\n')
    checks = []
    for name in NAMES[1:]:
        digest = hashlib.sha256((baseline / name).read_bytes()).hexdigest()
        checks.append(f'test "$(sha256sum web/{name} | cut -d \' \' -f 1)" = "{digest}"')
    script = script.replace('test -f .env', 'test -f .env\n' + '\n'.join(checks))
    script = script.replace("allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}", 'allowed = ' + repr(set(blobs)))
    script = script.replace('m.size < 500000', 'm.size < 10000000')
    script = script.replace('space-glass-release.tar.gz', 'design-system-release.tar.gz').replace('glass-upgrade-', 'design-system-upgrade-')
    script = script.replace('for name in glass-theme.css glass-theme.js news-ui.js index.html; do', 'for name in ' + ' '.join(NAMES) + '; do')
    script = script.replace("('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html')", repr(tuple(NAMES)))
    script = script.replace("'/api/resources?page=1&page_size=12')", "'/api/resources?page=1&page_size=12', '/api/ai/status')")
    script = script.replace('space-glass-manifest.json', 'design-system-manifest.json').replace('Glass frontend upgrade passed.', 'Shared design system upgrade passed.')
    (output / 'upgrade_design_system.sh').write_bytes(script.encode())
    (output / 'design-system-index.html').write_bytes(blobs['web/index.html'])
    print(json.dumps({'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': manifest['files']}))


if __name__ == '__main__':
    main()
