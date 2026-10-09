#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/space-news
archive=${1:-/root/space-admin-layout-20261008.tar.gz}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/admin-layout-upgrade-$stamp"
mkdir -m 700 "$evidence"
mkdir "$evidence/stage"
exec > >(tee "$evidence/run.log") 2>&1
old_app=$(docker compose ps -q app)
old_admin=$(docker compose --profile review ps -q admin)
test -n "$old_app" && test -n "$old_admin"
test "$(docker inspect "$old_admin" --format '{{.State.Running}}')" = true
old_admin_image=$(docker inspect "$old_admin" --format '{{.Image}}')
old_app_image=$(docker inspect "$old_app" --format '{{.Image}}')
image_name=$(docker inspect "$old_app" --format '{{.Config.Image}}')
old_volume=$(docker inspect "$old_admin" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
test -n "$old_volume"
python3 - "$archive" "$evidence/stage" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
allowed={'admin_web/index.html','admin_web/admin.css','admin_web/admin.js','admin_web/brand.svg','backend/admin_app.py','admin-layout-manifest.json'}
with tarfile.open(sys.argv[1],'r:gz') as bundle:
    members=bundle.getmembers()
    assert len(members)==len(allowed) and {m.name for m in members}==allowed
    assert all(m.isfile() and m.size<200000 for m in members)
    blobs={m.name:bundle.extractfile(m).read() for m in members}
manifest=json.loads(blobs['admin-layout-manifest.json'])
assert {r['path'] for r in manifest['files']}==allowed-{'admin-layout-manifest.json'}
current=Path('backend/admin_app.py').read_bytes().replace(b'\r\n',b'\n')
assert hashlib.sha256(current).hexdigest() in {manifest['admin_baseline_sha256'],hashlib.sha256(blobs['backend/admin_app.py']).hexdigest()}, 'Server admin backend differs; review before replacing'
for row in manifest['files']:
    assert hashlib.sha256(blobs[row['path']]).hexdigest()==row['sha256']
for name,data in blobs.items():
    path=Path(sys.argv[2])/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
print('Package validated:',manifest['release'])
PY
tar -czf "$evidence/source-before.tar.gz" admin_web backend/admin_app.py
if docker image inspect "$old_admin_image" >/dev/null 2>&1; then
  docker image tag "$old_admin_image" "space-admin-layout-rollback:$stamp"
else
  # A previous deployment pruned this old image; preserve the running admin filesystem.
  docker export "$old_admin" --output "$evidence/admin-runtime-before.tar"
  docker import --change 'WORKDIR /app' --change 'USER 10001:10001' \
    "$evidence/admin-runtime-before.tar" "space-admin-layout-rollback:$stamp" >/dev/null
fi
printf 'services:\n  admin:\n    image: space-admin-layout-rollback:%s\n' "$stamp" > "$evidence/rollback.yaml"
printf '%s\n' "$old_app" > "$evidence/public-container-before.txt"
mutated=0
rollback() {
  status=$?
  trap - ERR
  if [[ "$mutated" == 1 ]]; then
    tar -xzf "$evidence/source-before.tar.gz" -C "$PWD"
    docker image tag "$old_app_image" "$image_name"
    args=(-f compose.yaml)
    if [[ -f compose.override.yaml ]]; then args+=(-f compose.override.yaml); fi
    docker compose "${args[@]}" -f "$evidence/rollback.yaml" --profile review up -d --no-deps --no-build --force-recreate admin || true
  fi
  echo "Upgrade stopped ($status). Backup: $evidence"
  exit "$status"
}
trap rollback ERR
mutated=1
for name in admin_web/index.html admin_web/admin.css admin_web/admin.js admin_web/brand.svg backend/admin_app.py; do
  install -m 644 "$evidence/stage/$name" "$name"
done
docker compose build app
docker compose --profile review up -d --no-deps --no-build --force-recreate admin
new_admin=$(docker compose --profile review ps -q admin)
for attempt in $(seq 1 30); do
  state=$(docker inspect "$new_admin" --format '{{.State.Health.Status}}')
  if [[ "$state" == healthy ]]; then break; fi
  sleep 2
done
test "$state" = healthy
test "$(docker compose ps -q app)" = "$old_app"
test "$(docker inspect "$new_admin" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = "$old_volume"
docker compose --profile review exec -T admin python - <<'PY'
import hashlib,json,urllib.request,urllib.error
from pathlib import Path
for name in ('index.html','admin.css','admin.js','brand.svg'):
    path='/' if name=='index.html' else '/'+name
    with urllib.request.urlopen('http://127.0.0.1:8001'+path,timeout=10) as response:
        body=response.read()
    assert body==Path('/app/admin_web/'+name).read_bytes(),name
html=Path('/app/admin_web/index.html').read_text()
assert 'admin-sidebar' in html and 'config-section-extra-1' in html
try:
    urllib.request.urlopen('http://127.0.0.1:8001/api/resources',timeout=10)
except urllib.error.HTTPError as error:
    assert error.code==401
else:
    raise AssertionError('Admin auth must remain required')
print('Admin layout bytes, brand route and auth verified')
PY
docker compose exec -T app python - <<'PY'
import json,urllib.request
for path in ('/api/health','/api/news?page=1&page_size=10','/api/resources?page=1&page_size=12','/api/ai/status'):
    with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=10) as response:
        json.load(response)
print('Public service API checks passed; no paid queries')
PY
docker compose --profile review ps
echo "Admin layout upgrade passed. Evidence: $evidence"
