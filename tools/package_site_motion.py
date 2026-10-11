"""Publish approved motion and resource navigation without replacing live AI code."""
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT.parent / 'output/site-motion-preview'
NAMES = ['site-motion.css', 'site-motion.js', 'resource-navigation.html', 'index.html']


def patch_index(text):
    text = text.replace('\r\n', '\n')
    text = re.sub(r'(/assets/site-motion\.(?:css|js))\?v=[^" ]+',r'\1?v=20261009-usability-no-next',text)
    if '/assets/site-motion.css' not in text:
        text = text.replace('</head>', '<link rel="stylesheet" href="/assets/site-motion.css?v=20261009"></head>')
    if '/assets/site-motion.js' not in text:
        text = text.replace('</body>', '<script src="/assets/site-motion.js?v=20261009"></script></body>')
    text = text.replace('>资料下载</button>', '>资源导航</button>')
    text = text.replace('下一站，资料库。', '下一站，资源导航。').replace('浏览航天电子书与文件 →', '查看专业图书与官方机构入口 →')
    text = text.replace('<h2>资料库</h2><p>提供航天与工程学习资料的封面、书名、分类、格式、大小与下载入口，不提供PDF在线阅读。</p>',
                        '<h2>资源导航</h2><p>展示专业图书的封面、作者、出版社与内容简介，并提供官方机构入口；不提供书籍下载。</p>')
    return text


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--server-index', type=Path, required=True)
    args = parser.parse_args()
    css = (PREVIEW / 'site-motion.css').read_text(encoding='utf-8')
    css = re.sub(r'\.motion-preview-note\{[^}]*\}', '', css)
    js = (PREVIEW / 'site-motion.js').read_text(encoding='utf-8').replace("location.href='/editorial.html'", "location.href='/assets/resource-navigation.html'").replace("next.href='/editorial.html'", "next.href='/assets/resource-navigation.html'")
    navigation = (PREVIEW / 'editorial.html').read_text(encoding='utf-8')
    navigation = re.sub(r'<a href="http://127\.0\.0\.1:8871/navigation\.html">.*?</a>', '', navigation)
    navigation = navigation.replace('独立设计示例 · 资源由原站提供', '资源由原站提供')
    assert '127.0.0.1' not in navigation and '本地动效预览' not in navigation
    for name, text in [('site-motion.css', css), ('site-motion.js', js), ('resource-navigation.html', navigation)]:
        (ROOT / 'web' / name).write_text(text, encoding='utf-8')
    # Keep local changes from other tasks; the release index uses the live server baseline.
    local = ROOT / 'web/index.html'
    local.write_text(patch_index(local.read_text(encoding='utf-8')), encoding='utf-8')
    server_index = patch_index(args.server_index.read_text(encoding='utf-8'))
    assert 'data-motion-preview' not in server_index and 'AI 为演示回复' not in server_index
    blobs = {'web/'+name: (ROOT/'web'/name).read_bytes() for name in NAMES}
    blobs['web/index.html'] = server_index.encode()
    manifest = {'release':'site-motion-resource-navigation-20261009', 'files':[
        {'path':name, 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()} for name,data in blobs.items()]}
    blobs['manifest.json'] = (json.dumps(manifest, indent=2)+'\n').encode()
    output=ROOT/'artifacts/packages'; output.mkdir(exist_ok=True, parents=True)
    archive=output/'site-motion-release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in blobs.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644;tar.addfile(entry,io.BytesIO(data))
    script=(ROOT/'tools/upgrade_glass.sh').read_text(encoding='utf-8').replace('\r\n','\n')
    old="allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}"
    assert old in script
    script=script.replace(old,'allowed = '+repr(set(blobs)))
    script=script.replace('m.size < 500000','m.size < 10000000').replace('space-glass-release.tar.gz','site-motion-release.tar.gz').replace('glass-upgrade-','site-motion-upgrade-')
    script=script.replace('for name in glass-theme.css glass-theme.js news-ui.js index.html; do','for name in '+' '.join(NAMES)+'; do')
    script=script.replace("('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html')",repr(tuple(NAMES)))
    script=script.replace("'/api/resources?page=1&page_size=12')","'/api/resources?page=1&page_size=12', '/api/ai/status')")
    script=script.replace('test -f .env', '''test -f .env
expected_index=${2:?expected server index hash required}
test "$(sha256sum web/index.html | cut -d ' ' -f 1)" = "$expected_index"''')
    script=script.replace('Glass frontend upgrade passed.','Resource navigation and site motion upgrade passed.')
    (output/'upgrade_site_motion.sh').write_bytes(script.encode())
    print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'server_index_before':hashlib.sha256(args.server_index.read_bytes()).hexdigest()}))


if __name__=='__main__': main()
