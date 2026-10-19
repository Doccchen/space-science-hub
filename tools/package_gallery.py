"""Prepare a reviewable frontend snapshot; pending image rights block deployment."""
import hashlib
import io
import json
import tarfile
from pathlib import Path
try:
    from .build_styles import build
except ImportError:
    from build_styles import build

ROOT = Path(__file__).resolve().parents[1]

def main():
    build()
    # Include the existing news two-column UI and availability fixes used by index.
    # Backend changes are intentionally not bundled into this frontend-only snapshot.
    names = [
        'brand.svg','favicon.svg','studio.js','news-state.js','news-ui.js','news-reader.js',
        'news-agent-availability.js','news-agent.js','news-agent.css','resources-ui.js','ai-ui.js',
        'glass-theme.js','site-motion.js','resource-navigation.html','design-system.css',
        'styles/base.css','styles/components.css','styles/pages.css',
        'gallery.js','gallery-welcome.js','gallery-slides.json',
        'tiangong-lineart-v2.png','long-march-5-lineart-transparent.png','shenzhou-lineart-transparent.png',
        'satellite-lineart-transparent.png','change-6-lander-ascender-lineart-v2.png',
    ]
    slides = json.loads((ROOT/'web/gallery-slides.json').read_text(encoding='utf-8'))
    images = [v['path'].removeprefix('/assets/') for s in slides for v in s['variants']]
    names.extend(images)
    names.append('index.html')  # Asset publication must precede the entry point.
    assert len(names)==len(set(names))
    blobs = {'web/'+name:(ROOT/'web'/name).read_bytes() for name in names}
    manifest = {'release':'zhihang-gallery-restored-20261017',
                'deployable':all(s['rights_status']=='authorized' and s['rights_evidence'] for s in slides),
                'includes_existing_news_split':True,
                'files':[{'path':name,'size':len(blob),'sha256':hashlib.sha256(blob).hexdigest()} for name,blob in blobs.items()]}
    blobs['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    output=ROOT/'artifacts/gallery-release';output.mkdir(parents=True,exist_ok=True)
    archive=output/'zhihang-gallery-restored-20261017.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,blob in blobs.items():
            member=tarfile.TarInfo(name);member.size=len(blob);member.mode=0o644;tar.addfile(member,io.BytesIO(blob))
    (output/'manifest.json').write_bytes(blobs['manifest.json'])
    (output/'sha256.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    script=(ROOT/'tools/upgrade_glass.sh').read_text(encoding='utf-8').replace('\r\n','\n')
    script=script.replace("allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}",
                          'allowed = '+repr(set(blobs)))
    script=script.replace('m.size < 500000','m.size <= 4000000')
    script=script.replace("manifest = json.loads(blobs['manifest.json'])", "manifest = json.loads(blobs['manifest.json'])\nassert manifest.get('deployable') is True, 'Image public-display rights pending; local package only'")
    script=script.replace('space-glass-release.tar.gz',archive.name).replace('glass-upgrade-','gallery-upgrade-')
    script=script.replace('for name in glass-theme.css glass-theme.js news-ui.js index.html; do','for name in '+' '.join(names)+'; do')
    script=script.replace("('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html')",repr(tuple(names)))
    script=script.replace('install -m 644 "$evidence/stage/web/$name" "web/$name"','install -D -m 644 "$evidence/stage/web/$name" "web/$name"')
    script=script.replace('# Assets first, index last; existing clients can continue loading old assets.',
                          '# Assets first, index last; existing clients can continue loading old assets.\ndocker exec -u 0 "$old" mkdir -p /app/web/styles /app/web/gallery')
    script=script.replace('test -f .env','''test -f .env
expected_index=${2:?reviewed live index SHA256 required}
test "$(sha256sum web/index.html | cut -d ' ' -f 1)" = "$expected_index"''')
    script=script.replace('Glass frontend upgrade passed.','Gallery frontend upgrade passed.')
    (output/'upgrade_gallery.sh').write_text(script,encoding='utf-8',newline='\n')
    validate(archive)
    print(json.dumps({'archive':str(archive),'files':len(names),'bytes':archive.stat().st_size,'deployable':manifest['deployable']}))

def validate(archive):
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        assert len({m.name for m in members})==len(members)
        assert all(m.isfile() and m.size<=4000000 and '..' not in Path(m.name).parts for m in members)
        blobs={m.name:tar.extractfile(m).read() for m in members}
    manifest=json.loads(blobs.pop('manifest.json'))
    assert set(blobs)=={s['path'] for s in manifest['files']}
    for s in manifest['files']:
        assert len(blobs[s['path']])==s['size']
        assert hashlib.sha256(blobs[s['path']]).hexdigest()==s['sha256']
    slides=json.loads(blobs['web/gallery-slides.json'])
    for slide in slides:
        for variant in slide['variants']:
            blob=blobs['web/'+variant['path'].removeprefix('/assets/')]
            assert hashlib.sha256(blob).hexdigest()==variant['sha256']

if __name__=='__main__':
    main()
