#!/usr/bin/env bash
# Run on the existing server after backfill; only pauses/recreates this app.
set -Eeuo pipefail
cd /opt/space-news
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/final-acceptance-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
restore_scheduler() {
  COLLECT_ENABLED=1 docker compose up -d --no-deps app || true
}
trap restore_scheduler EXIT
wait_healthy() {
  for attempt in $(seq 1 60); do
    container=$(docker compose ps -q app)
    if [[ -n "$container" ]] && [[ $(docker inspect "$container" --format '{{.State.Health.Status}}') == healthy ]]; then return; fi
    sleep 2
  done
  echo "Application did not become healthy"
  return 1
}
# Keep the snapshot stable while asserting every paginated API and data identity.
COLLECT_ENABLED=0 docker compose up -d --no-deps app
wait_healthy
docker compose exec -T app python -m tools.accept_domestic before > "$evidence/before.log"
old_container=$(docker compose ps -q app)
COLLECT_ENABLED=0 docker compose up -d --force-recreate --no-deps app
wait_healthy
new_container=$(docker compose ps -q app)
[[ "$old_container" != "$new_container" ]]
docker compose exec -T app python -m tools.accept_domestic after > "$evidence/after.log"
docker cp "$new_container:/data/domestic-acceptance/result.json" "$evidence/result.json"
printf 'before=%s\nafter=%s\n' "$old_container" "$new_container" > "$evidence/containers.txt"
COLLECT_ENABLED=1 docker compose up -d --no-deps app
wait_healthy
docker compose ps
docker stats --no-stream > "$evidence/container-stats.txt"
docker compose exec -T app python - <<'PY'
import json
from pathlib import Path
from urllib.request import urlopen
r=json.loads(Path('/data/domestic-acceptance/result.json').read_text())
with urlopen('http://127.0.0.1:8000/api/health', timeout=5) as response:
    health=json.load(response)
print(json.dumps({'health':health,'sources':{key:value['stored'] for key,value in r['sources'].items()},
                  'categories':r['categories'],'container_recreation':r['container_recreation'],
                  'backup_restore':r['isolated_backup_restore'],
                  'browser_interaction':'requires user verification',
                  'historical_coverage':'CNSA stopped at date window; CMSE retains 41 old-archive exceptions'},
                 ensure_ascii=False, indent=2))
PY
echo "Final server checks passed; evidence: $evidence"
