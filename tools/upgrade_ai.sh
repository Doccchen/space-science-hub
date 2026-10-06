#!/usr/bin/env bash
# Operator-run release; checks never call the paid AI endpoint.
set +x
set -Eeuo pipefail
umask 077
cd /opt/space-news
test -f /root/space-ai-release.tar.gz
test -f /root/install_ai_release.py
test -f .env
old=$(docker compose ps -q app)
test -n "$old"
old_image=$(docker inspect "$old" --format '{{.Image}}')
image_name=$(docker inspect "$old" --format '{{.Config.Image}}')
old_volume=$(docker inspect "$old" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
test -n "$old_volume"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/ai-upgrade-$stamp"
mkdir -m 700 "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
echo "AI release preflight; evidence: $evidence"
python3 /root/install_ai_release.py --archive /root/space-ai-release.tar.gz --stage "$evidence/stage"
python3 /root/install_ai_release.py --compose compose.yaml --output "$evidence/compose.candidate.yaml"
tar -czf "$evidence/code-before.tar.gz" backend web compose.yaml
mkdir "$evidence/runtime-web"
docker cp "$old:/app/web/." "$evidence/runtime-web/"
cp -p .env "$evidence/env-before"
printf '%s\n' "$old_image" > "$evidence/image-before.txt"
printf '%s\n' "$old_volume" > "$evidence/volume-before.txt"
# Snapshot news consistently without stopping collection. AI has its own database.
docker exec -i "$old" python - "$stamp" <<'PY'
import json,sqlite3,sys,urllib.request
from pathlib import Path
directory=Path('/tmp/ai-before-'+sys.argv[1]);directory.mkdir()
with sqlite3.connect('/data/news.sqlite3') as source,sqlite3.connect(directory/'news.sqlite3') as dest:source.backup(dest)
with sqlite3.connect(directory/'news.sqlite3') as db:
    rows=db.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id').fetchall()
with urllib.request.urlopen('http://127.0.0.1:8000/api/resources?page=1&page_size=12') as response:resources=json.load(response)['total']
(directory/'before.json').write_text(json.dumps({'articles':rows,'resources':resources}))
if Path('/data/ai.sqlite3').exists():
    with sqlite3.connect('/data/ai.sqlite3') as source,sqlite3.connect(directory/'ai.sqlite3') as dest:source.backup(dest)
print('Existing news/resources snapshotted; no paid calls.')
PY
docker cp "$old:/tmp/ai-before-$stamp/." "$evidence/"
mutated=0
replaced=0
rollback() {
  local status=$?
  trap - ERR
  echo "Upgrade failed ($status); restoring previous source/configuration/image, keeping current data."
  if [[ "$mutated" == 1 ]]; then
    tar -xzf "$evidence/code-before.tar.gz" -C "$PWD" || true
    cp -p "$evidence/env-before" .env || true
    docker image tag "$old_image" "$image_name" || true
  fi
  if [[ "$replaced" == 1 ]]; then
    docker compose up -d --no-build --force-recreate --no-deps app || true
    restored=$(docker compose ps -q app)
    if [[ -n "$restored" ]]; then docker cp "$evidence/runtime-web/." "$restored:/app/web/" || true; fi
  fi
  echo "Evidence: $evidence. Backups contain private data; keep them on the server."
  exit "$status"
}
trap rollback ERR
mutated=1
python3 - "$evidence/stage" <<'PY'
import json,shutil,sys
from pathlib import Path
root=Path(sys.argv[1]);manifest=json.loads((root/'manifest.json').read_text())
for item in manifest['files']:
    target=Path(item['path']);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/item['path'],target);target.chmod(0o644)
PY
cp "$evidence/compose.candidate.yaml" compose.yaml
docker compose config --quiet
docker compose build app
# All upstream interactions in this test file are offline fakes/MockTransport.
docker compose run --rm --no-deps -e AI_ENABLED=0 -e DASHSCOPE_API_KEY= -e COLLECT_ENABLED=0 \
  -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -p test_ai.py -v
replaced=1
docker compose up -d --no-build --no-deps app
healthy=0
for attempt in $(seq 1 30); do
  new=$(docker compose ps -q app)
  if [[ -n "$new" && $(docker inspect "$new" --format '{{.State.Health.Status}}') == healthy ]]; then healthy=1;break;fi
  sleep 2
done
test "$healthy" == 1
new_volume=$(docker inspect "$new" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
test "$new_volume" = "$old_volume"
docker cp "$evidence/before.json" "$new:/tmp/ai-before.json"
docker cp "$evidence/stage/manifest.json" "$new:/tmp/ai-release-manifest.json"
docker exec -i -u 0 "$new" python - <<'PY'
import hashlib,json,sqlite3,urllib.request
from pathlib import Path
base='http://127.0.0.1:8000'
def api(path):
    with urllib.request.urlopen(base+path,timeout=10) as response:return json.load(response)
before=json.loads(Path('/tmp/ai-before.json').read_text())
with sqlite3.connect('/data/news.sqlite3') as db:
    rows={row[0]:list(row) for row in db.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles')}
assert all(rows.get(row[0])==row for row in before['articles']),'Existing news identities changed'
assert api('/api/resources?page=1&page_size=12')['total']==before['resources'],'Resource catalog changed'
assert api('/api/health')['status']=='ok'
status=api('/api/ai/status')
assert status['enabled'],status['message']
for item in json.loads(Path('/tmp/ai-release-manifest.json').read_text())['files']:
    if item['path'].startswith('tests/'):continue
    assert hashlib.sha256((Path('/app')/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
for name in ('ai.css','ai-ui.js','studio.js','glass-theme.js'):
    with urllib.request.urlopen(base+'/assets/'+name,timeout=10) as response:assert response.read()==(Path('/app/web')/name).read_bytes()
with urllib.request.urlopen(base+'/',timeout=10) as response:assert b'id="ai-form"' in response.read()
print(json.dumps({'ai_enabled':True,'old_news_preserved':len(before['articles']),'resources':before['resources'],
                  'frontend_hashes':'passed','paid_test_calls':0},ensure_ascii=False))
PY
docker compose ps
echo "AI website upgrade passed. Evidence: $evidence"
echo "No paid verification calls were made. Open #home, Ctrl+F5, then ask when ready."
