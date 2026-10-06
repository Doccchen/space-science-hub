#!/usr/bin/env bash
# Frontend-only release for the existing space-news deployment.
set -Eeuo pipefail
cd /opt/space-news
archive=${1:-/root/space-glass-release.tar.gz}
test -f "$archive"
test -f .env
old=$(docker compose ps -q app)
test -n "$old"
test "$(docker inspect "$old" --format '{{.State.Running}}')" = true
old_image=$(docker inspect "$old" --format '{{.Image}}')
image_name=$(docker inspect "$old" --format '{{.Config.Image}}')
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/glass-upgrade-$stamp"
mkdir -p "$evidence/stage" "$evidence/runtime-backup"
exec > >(tee "$evidence/run.log") 2>&1
echo "Frontend release preflight; evidence: $evidence"
# Refuse an older API: the current UI requires numbered pagination.
docker compose exec -T app python - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/api/news?page=1&page_size=10', timeout=15) as response:
    data = json.load(response)
assert isinstance(data.get('page'), int) and isinstance(data.get('total_pages'), int), 'Deploy the numbered-pagination backend before this frontend release'
assert data.get('page_size') == 10, 'Numbered-pagination API is required'
print('Numbered-pagination API available; articles:', data['total'])
PY
# Extract only the four expected files after checking the archive and manifest.
python3 - "$archive" "$evidence/stage" <<'PY'
import hashlib, json, sys, tarfile
from pathlib import Path
allowed = {'web/index.html', 'web/news-ui.js', 'web/glass-theme.css', 'web/glass-theme.js', 'manifest.json'}
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    members = archive.getmembers()
    assert len(members) == len(allowed) and {m.name for m in members} == allowed, 'Unexpected release contents'
    assert all(m.isfile() and m.size < 500000 for m in members), 'Invalid release member'
    blobs = {m.name: archive.extractfile(m).read() for m in members}
manifest = json.loads(blobs['manifest.json'])
assert {item['path'] for item in manifest['files']} == allowed - {'manifest.json'}
for item in manifest['files']:
    assert hashlib.sha256(blobs[item['path']]).hexdigest() == item['sha256'], 'Release checksum mismatch'
for name, content in blobs.items():
    path = Path(sys.argv[2]) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o644)
print('Release validated:', manifest['release'])
PY
# Both source and running container are backed up before the first write.
tar -czf "$evidence/source-web-before.tar.gz" web
docker cp "$old:/app/web/." "$evidence/runtime-backup/"
printf '%s\n' "$old" > "$evidence/container-id.txt"
docker inspect "$old" --format '{{.Image}}' > "$evidence/image-id.txt"
docker inspect "$old" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' > "$evidence/data-volume.txt"
mutated=0
rollback() {
  local status=$?
  trap - ERR
  if [[ "$mutated" == 1 ]]; then
    echo "Frontend verification failed; restoring backed-up source and container files."
    tar -xzf "$evidence/source-web-before.tar.gz" -C "$PWD" || true
    docker cp "$evidence/runtime-backup/." "$old:/app/web/" || true
    docker image tag "$old_image" "$image_name" || true
  fi
  echo "Stopped (status=$status). Evidence: $evidence"
  exit "$status"
}
trap rollback ERR
mutated=1
# Update the existing server source, then build the persistent image without restarting.
for name in glass-theme.css glass-theme.js news-ui.js index.html; do
  install -m 644 "$evidence/stage/web/$name" "web/$name"
done
docker compose build app
# Assets first, index last; existing clients can continue loading old assets.
for name in glass-theme.css glass-theme.js news-ui.js index.html; do
  docker cp "web/$name" "$old:/app/web/$name"
done
# Compare served bytes against the exact release and check API availability.
docker compose exec -T app python - < <(cat <<'PY'
import hashlib, json, urllib.request
from pathlib import Path
base = 'http://127.0.0.1:8000'
for name in ('glass-theme.css', 'glass-theme.js', 'news-ui.js', 'index.html'):
    url = base + ('/' if name == 'index.html' else '/assets/' + name)
    with urllib.request.urlopen(url, timeout=15) as response:
        served = response.read()
    expected = (Path('/app/web') / name).read_bytes()
    assert served == expected, f'Served asset differs: {name}'
    print(name, hashlib.sha256(served).hexdigest())
for endpoint in ('/api/health', '/api/news?page=1&page_size=20', '/api/resources?page=1&page_size=12'):
    with urllib.request.urlopen(base + endpoint, timeout=15) as response:
        result = json.load(response)
    print(endpoint, {key: result[key] for key in ('status','total','page','page_size','total_pages','pages') if key in result})
print('Frontend HTTP checks passed')
PY
)
docker cp "$evidence/stage/manifest.json" "$old:/tmp/space-glass-manifest.json"
docker compose exec -T app python - <<'PY'
import hashlib, json
from pathlib import Path
for item in json.loads(Path('/tmp/space-glass-manifest.json').read_text())['files']:
    assert hashlib.sha256((Path('/app') / item['path']).read_bytes()).hexdigest() == item['sha256'], item['path']
print('Container release hashes verified')
PY
test "$(docker compose ps -q app)" = "$old"
docker compose ps
echo "Glass frontend upgrade passed. Image built and live assets updated without container restart. Evidence: $evidence"
echo "Source and image were updated so future container recreations retain this frontend."
echo "Refresh the browser with Ctrl+F5 and check news filters/pagination, reading, and resource downloads."
