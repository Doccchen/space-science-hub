"""Patch only the AI page and package a rollback-capable frontend release."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ['ai-layout.css', 'ai-ui.js', 'tiangong-lineart-v2.png',
         'long-march-5-lineart-transparent.png', 'shenzhou-lineart-transparent.png',
         'satellite-lineart-transparent.png', 'index.html']
AI_MAIN = '''<main id="home" class="page hidden ai-stage" data-ai-conversation="false">
<img class="ai-art ai-art-station" src="/assets/tiangong-lineart-v2.png" alt="" aria-hidden="true">
<img class="ai-art ai-art-rocket" src="/assets/long-march-5-lineart-transparent.png" alt="" aria-hidden="true">
<img class="ai-art ai-art-shenzhou" src="/assets/shenzhou-lineart-transparent.png" alt="" aria-hidden="true">
<img class="ai-art ai-art-satellite" src="/assets/satellite-lineart-transparent.png" alt="" aria-hidden="true">
<div class="ai-toolbar"><span class="eyebrow">02 / KNOWLEDGE WORKSPACE</span><button id="ai-new" class="secondary" type="button">新对话 ↻</button></div>
<div class="ai-service-state ai-sr-only"><span id="ai-status-dot" class="ai-status-dot" aria-hidden="true"></span><span id="ai-service-text" role="status">正在检查问答服务…</span></div>
<div class="ai-body"><div class="ai-workspace">
<div id="ai-welcome" class="ai-welcome"><h2>你想了解什么？</h2><p id="ai-welcome-copy">基于本站专属知识库，把专业概念讲清楚。</p></div>
<div id="ai-thread" class="ai-thread" aria-label="问答记录" aria-busy="false"></div><p id="ai-complete" class="ai-sr-only" role="status" aria-live="polite"></p>
<div id="ai-waiting" class="ai-waiting" role="status" hidden><span aria-hidden="true"></span>正在检索资料并整理回答，请稍候…</div><p id="ai-feedback" role="status"></p>
<form id="ai-form" class="ai-composer"><label for="ai-question">向知识库提问</label><textarea id="ai-question" maxlength="1500" placeholder="例如：固体火箭发动机为什么能产生推力？" disabled></textarea><div class="ai-compose-actions"><button id="ai-send" type="submit" disabled>发送问题 ↑</button></div></form>
</div><p class="ai-footer-note">知航 / 从地球，望向更远处。</p></div>
</main>'''


def patch_index(text):
    text = text.replace('\r\n', '\n')
    text, count = re.subn(r'<main id="home"[^>]*>.*?</main>', AI_MAIN, text, flags=re.S)
    assert count == 1, 'Exactly one AI page required'
    text = re.sub(r'<link rel="stylesheet" href="/assets/ai-layout\.css[^" ]*">', '', text)
    text = text.replace('</head>', '<link rel="stylesheet" href="/assets/ai-layout.css?v=20261008-approved"></head>')
    text = text.replace('/assets/ai-ui.js?v=20261007-ui', '/assets/ai-ui.js?v=20261008-approved')
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--server-index', type=Path)
    args = parser.parse_args()
    output = ROOT / 'artifacts/packages'
    output.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        local = ROOT / 'web/index.html'
        local.write_text(patch_index(local.read_text(encoding='utf-8')), encoding='utf-8')
        # Stageable index contains only this task; retain other local edits in the worktree.
        baseline = subprocess.check_output(['git', 'show', 'HEAD:web/index.html'], cwd=ROOT).decode()
        (output / 'ai-index-commit.html').write_text(patch_index(baseline), encoding='utf-8')
    source = args.server_index or ROOT / 'web/index.html'
    blobs = {'web/' + name: (ROOT / 'web' / name).read_bytes() for name in NAMES}
    blobs['web/index.html'] = patch_index(source.read_text(encoding='utf-8')).encode()
    manifest = {'release': 'ai-workspace-lineart-20261008', 'files': [
        {'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
        for name, data in blobs.items()]}
    blobs['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    archive = output / 'ai-layout-release.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in blobs.items():
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    script = (ROOT / 'tools/upgrade_glass.sh').read_text(encoding='utf-8').replace('\r\n', '\n')
    original = "allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}"
    assert original in script
    script = script.replace(original, 'allowed = ' + repr(set(blobs)))
    script = script.replace('m.size < 500000', 'm.size < 10000000')
    script = script.replace('space-glass-release.tar.gz', 'ai-layout-release.tar.gz')
    script = script.replace('glass-upgrade-', 'ai-layout-upgrade-')
    script = script.replace('for name in glass-theme.css glass-theme.js news-ui.js index.html; do',
                            'for name in ' + ' '.join(NAMES) + '; do')
    script = script.replace("('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html')", repr(tuple(NAMES)))
    script = script.replace("'/api/resources?page=1&page_size=12')", "'/api/resources?page=1&page_size=12', '/api/ai/status')")
    script = script.replace('test -f .env', '''test -f .env
expected_index=${2:?expected server index SHA256 required}
test "$(sha256sum web/index.html | cut -d ' ' -f 1)" = "$expected_index"''')
    script = script.replace('Glass frontend upgrade passed.', 'AI workspace upgrade passed.')
    (output / 'upgrade_ai_layout.sh').write_bytes(script.encode())
    print(json.dumps({'archive': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'source_index_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
