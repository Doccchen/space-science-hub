"""Package only the four frontend files for the glass-theme release."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    output = ROOT / 'artifacts/packages'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'space-glass-release.tar.gz'
    files = {}
    for name in ('index.html', 'news-ui.js', 'glass-theme.css', 'glass-theme.js'):
        files['web/' + name] = (ROOT / 'web' / name).read_bytes().replace(b'\r\n', b'\n')
    manifest = {'release': 'space-glass-20261006', 'files': [
        {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()]}
    files['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    with tarfile.open(archive, 'w:gz') as tar:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), 0o644
            tar.addfile(entry, io.BytesIO(data))
    (output / 'space-glass-release.manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Separate script uses LF and can be run before any server files are changed.
    (output / 'upgrade_glass.sh').write_bytes((ROOT / 'tools/upgrade_glass.sh').read_bytes().replace(b'\r\n', b'\n'))
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
