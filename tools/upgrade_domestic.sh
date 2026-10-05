#!/usr/bin/env bash
# Run in the existing /opt/space-news checkout after uploading the new release.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/domestic-upgrade-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
resume_scheduler() {
  COLLECT_ENABLED=1 docker compose up -d --no-deps app || true
}
trap 'echo "Upgrade stopped at line $LINENO. See evidence logs."; resume_scheduler' ERR
old=$(docker compose ps -q app)
[[ -n "$old" ]]
cp -p .env "$evidence/env-backup"
docker compose exec -T app python - <<'PY'
import json, sqlite3
from pathlib import Path
db=sqlite3.connect('/data/news.sqlite3')
db.row_factory=sqlite3.Row
rows=[dict(row) for row in db.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id')]
Path('/data/upgrade-baseline.json').write_text(json.dumps(rows))
target=sqlite3.connect('/data/pre-domestic-upgrade.sqlite3')
db.backup(target)
target.close(); db.close()
PY
docker cp "$old:/data/pre-domestic-upgrade.sqlite3" "$evidence/pre-upgrade.sqlite3"
docker cp "$old:/data/upgrade-baseline.json" "$evidence/old-identities.json"
docker image inspect space-news-app --format '{{.Id}}' > "$evidence/previous-image-id.txt"
docker compose build
# Disable the scheduler while doing migration, probes and acceptance; restore at end.
COLLECT_ENABLED=0 docker compose up -d --no-deps app
wait_ready() {
  for attempt in $(seq 1 60); do
    if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" 2>/dev/null; then return; fi
    sleep 2
  done
  return 1
}
wait_ready
docker compose run --rm --no-deps -e COLLECT_ENABLED=0 -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -v
for source in cnsa cmse cas_space landspace; do
  if docker compose exec -T app python -m backend.manage probe "$source" --enable > "$evidence/$source-probe.json" 2> "$evidence/$source-probe-error.log"; then
    echo "$source: probe and enable succeeded"
  else
    echo "$source: not enabled; see $evidence/$source-probe-error.log"
  fi
done
docker compose exec -T app python -m backend.manage collect > "$evidence/collection.json"
docker compose exec -T app python -m tools.accept_domestic before
before=$(docker compose ps -q app)
volume=$(docker inspect "$before" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
COLLECT_ENABLED=0 docker compose up -d --force-recreate --no-deps app
wait_ready
after=$(docker compose ps -q app)
new_volume=$(docker inspect "$after" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ -n "$volume" && "$before" != "$after" && "$volume" == "$new_volume" ]]
docker compose exec -T app python -m tools.accept_domestic after
docker cp "$after:/data/domestic-acceptance/result.json" "$evidence/result.json"
printf 'before=%s\nafter=%s\nvolume=%s\n' "$before" "$after" "$volume" > "$evidence/containers.txt"
COLLECT_ENABLED=1 docker compose up -d --no-deps app
wait_ready
docker stats --no-stream > "$evidence/container-stats.txt"
docker compose ps
echo "Enabled-source checks passed; see result.json for actual sources. Historical backfill and browser checks remain separate. Evidence: $evidence"
