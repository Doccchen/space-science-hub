"""Magazine frontend-only release, with the established hot-update rollback."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
NAMES=['brand.svg','favicon.svg','news-state.js','frontend-refinement.css','glass-theme.css',
       'glass-theme.js','ai.css','news-ui.js','news-reader.js','resources-ui.js','ai-ui.js','quiet-ui.css',
       'editorial.css','earthrise.jpg','history-mengtian.jpg','history-tianhe.png',
       'history-apollo11.jpg','history-rosetta.jpg','history-slides.json','history-carousel.js','index.html']


def main():
    output=ROOT/'artifacts/packages';output.mkdir(parents=True,exist_ok=True)
    # Preserve binary image bytes; normalize only the source text.
    files={}
    for name in NAMES:
        data=(ROOT/'web'/name).read_bytes()
        if Path(name).suffix in {'.js','.css','.html','.svg','.json'}:
            data=data.replace(b'\r\n',b'\n')
        files['web/'+name]=data
    manifest={'release':'space-frontend-magazine-carousel-20261007','files':[
        {'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()]}
    files['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    archive=output/'space-frontend-magazine-release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,data in files.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644;tar.addfile(entry,io.BytesIO(data))
    (output/'space-frontend-magazine-release.manifest.json').write_bytes(files['manifest.json'])
    (output/'space-frontend-magazine-release.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n',encoding='ascii')
    script=(ROOT/'tools/upgrade_glass.sh').read_text(encoding='utf-8').replace('\r\n','\n')
    old_allow="allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}"
    assert old_allow in script
    script=script.replace(old_allow,'allowed = {'+', '.join(repr(name) for name in sorted(files))+'}')
    script=script.replace("m.size < 500000", "m.size < (1500000 if m.name == 'web/history-tianhe.png' else 500000)")
    script=script.replace('space-glass-release.tar.gz','space-frontend-magazine-release.tar.gz').replace('glass-upgrade-','magazine-upgrade-')
    assert script.count('for name in glass-theme.css glass-theme.js news-ui.js index.html; do')==2
    script=script.replace('for name in glass-theme.css glass-theme.js news-ui.js index.html; do','for name in '+' '.join(NAMES)+'; do')
    old_tuple="('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html')"
    assert old_tuple in script
    script=script.replace(old_tuple,repr(tuple(NAMES))).replace('space-glass-manifest.json','space-frontend-manifest.json')
    script=script.replace("(\'/api/health\', \'/api/news?page=1&page_size=20\', \'/api/resources?page=1&page_size=12\')",
                          "('/api/health', '/api/news?page=1&page_size=10', '/api/resources?page=1&page_size=12', '/api/ai/status')")
    marker='# Extract only the four expected files after checking the archive and manifest.'
    assert marker in script
    preflight="""# Existing AI page assets/API are required; no paid query is made.
docker compose exec -T app python - <<'PY'
import json,urllib.request
from pathlib import Path
assert Path('/app/web/ai-ui.js').is_file(), 'Deploy the AI website release before this frontend update'
with urllib.request.urlopen('http://127.0.0.1:8000/api/ai/status',timeout=10) as response:
    status=json.load(response)
assert isinstance(status.get('enabled'),bool), 'AI status API required'
print('AI status API available; no paid calls.')
PY
# Extract only the expected frontend files after checking the archive and manifest.
"""
    script=script.replace(marker,preflight).replace('Glass frontend upgrade passed.','Frontend refinement upgrade passed.')
    script=script.replace('the four expected files','the expected frontend files')
    script=script.replace('Refresh the browser with Ctrl+F5 and check news filters/pagination, reading, and resource downloads.',
                          'Refresh with Ctrl+F5; check immersive cover, news filters/pagination, reading close/back, AI status and resource downloads.')
    (output/'upgrade_magazine.sh').write_bytes(script.encode())
    print(json.dumps({'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
