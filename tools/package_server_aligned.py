"""Local snapshot based on the freshly captured public server frontend."""
import hashlib
import io
import json
import tarfile
from pathlib import Path
try:
    from .build_styles import build, GROUPS
except ImportError:
    from build_styles import build, GROUPS

ROOT=Path(__file__).resolve().parents[1]

def main():
    build()
    baseline_path=ROOT/'content/releases/server-baseline-20261017.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
    names={r['path'] for r in baseline['files']}
    names.add('tools/build_styles.py')
    names.update('web/'+n for group in GROUPS.values() for n in group)
    names.update(['web/site-welcome.js','web/site-welcome.css','web/history-slides.json','web/carousel-additions.json'])
    names.add('web/professional-books.js')
    books=json.loads((ROOT/'content/professional-books.json').read_text(encoding='utf-8'))
    names.update('web/book-covers/'+b['id']+'.webp' for b in books)
    additions=json.loads((ROOT/'web/carousel-additions.json').read_text(encoding='utf-8'))
    for slide in additions:
        names.update('web/'+v['path'].removeprefix('/assets/') for v in slide['variants'])
    names=sorted(names-{'web/index.html'})+['web/index.html']
    blobs={name:(ROOT/name).read_bytes() for name in names}
    deployable=all(s.get('rights_status')=='authorized_user_confirmed' and s.get('rights_evidence') for s in additions)
    manifest={'release':'server-baseline-welcome-split-carousel12-books27-20261017','deployable':deployable,
              'baseline':baseline,'changes':['first-visit welcome','two-column news reader','5 original + 7 Landspace slides'],
              'files':[{'path':n,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in blobs.items()]}
    blobs['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    out=ROOT/'artifacts/server-aligned-release-20261017';out.mkdir(parents=True,exist_ok=True)
    archive=out/'server-aligned-local.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for name,blob in blobs.items():
            m=tarfile.TarInfo(name);m.size=len(blob);m.mode=0o644;t.addfile(m,io.BytesIO(blob))
    with tarfile.open(archive) as t:
        assert {m.name for m in t.getmembers()}==set(blobs)
        for name,blob in blobs.items():assert t.extractfile(name).read()==blob
    (out/'manifest.json').write_bytes(blobs['manifest.json'])
    (out/'sha256.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    print(json.dumps({'archive':str(archive),'files':len(names),'deployable':deployable,'bytes':archive.stat().st_size}))

if __name__=='__main__':main()
