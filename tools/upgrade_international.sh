#!/usr/bin/env bash
# Selected batch only. Preserves old article identities and every backfill queue row.
set -Eeuo pipefail
cd /opt/space-news
batch=${1:-1}
case "$batch" in
  1) batch_sources=(spacex blue_origin arianespace ispace) ;;
  2) batch_sources=(skyroot gilmour) ;;
  *) echo "Usage: bash tools/upgrade_international.sh [1|2]"; exit 1 ;;
esac
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/international-upgrade-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
restore_scheduler() { COLLECT_ENABLED=1 docker compose up -d --no-deps app || true; }
trap restore_scheduler EXIT
wait_healthy() {
  for attempt in $(seq 1 60); do
    id=$(docker compose ps -q app)
    if [[ -n "$id" && $(docker inspect "$id" --format '{{.State.Health.Status}}') == healthy ]]; then return; fi
    sleep 2
  done
  return 1
}
old=$(docker compose ps -q app)
[[ -n "$old" ]]
cp -p .env "$evidence/env-backup"
docker compose exec -T app python - <<'PY'
import sqlite3,json
from pathlib import Path
db=sqlite3.connect('/data/news.sqlite3');db.row_factory=sqlite3.Row
articles=[dict(row) for row in db.execute('SELECT id,source_id,canonical_url,first_seen_at FROM articles ORDER BY id')]
Path('/data/upgrade-baseline.json').write_text(json.dumps(articles))
state={name:[dict(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in ('backfill_runs','backfill_items')}
Path('/data/pre-international-queues.json').write_text(json.dumps(state))
target=sqlite3.connect('/data/pre-international.sqlite3');db.backup(target);target.close();db.close()
PY
docker cp "$old:/data/pre-international.sqlite3" "$evidence/pre-upgrade.sqlite3"
docker cp "$old:/data/upgrade-baseline.json" "$evidence/article-baseline.json"
docker cp "$old:/data/pre-international-queues.json" "$evidence/queue-baseline.json"
docker compose build
COLLECT_ENABLED=0 docker compose up -d --no-deps app
wait_healthy
docker compose run --rm --no-deps -e COLLECT_ENABLED=0 -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -v
docker compose exec -T app python - <<'PY'
import sqlite3,json
from pathlib import Path
db=sqlite3.connect('/data/news.sqlite3');db.row_factory=sqlite3.Row
before=json.loads(Path('/data/pre-international-queues.json').read_text())
after={name:[dict(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in before}
assert before==after,'International upgrade changed prior backfill jobs/failed rows'
print('Historical jobs and failed queues preserved')
PY
for source in "${batch_sources[@]}"; do
  if docker compose exec -T app python -m backend.manage probe "$source" --enable > "$evidence/$source-probe.json" 2> "$evidence/$source-probe-error.log"; then
    echo "$source: enabled after three live news samples"
  else
    echo "$source: not enabled; inspect $evidence/$source-probe-error.log"
  fi
done
# At least one verified international company is required for this batch's acceptance.
docker compose exec -T app python - "${batch_sources[@]}" <<'PY'
import sys
from backend import news
enabled=[row['id'] for row in news.sources_status() if row['id'] in sys.argv[1:] and row['enabled'] and row['region']=='international' and row['publisher_kind']=='company']
assert enabled,'No selected-batch international company enabled; this batch cannot pass'
print('Actual enabled selected-batch company sources:',enabled)
PY
docker compose exec -T app python -m backend.manage collect > "$evidence/collection.json"
docker compose exec -T app python -m tools.accept_domestic before > "$evidence/accept-before.log"
before=$(docker compose ps -q app)
COLLECT_ENABLED=0 docker compose up -d --force-recreate --no-deps app
wait_healthy
after=$(docker compose ps -q app)
[[ "$before" != "$after" ]]
docker compose exec -T app python -m tools.accept_domestic after > "$evidence/accept-after.log"
docker cp "$after:/data/domestic-acceptance/result.json" "$evidence/result.json"
printf 'before=%s\nafter=%s\n' "$before" "$after" > "$evidence/containers.txt"
COLLECT_ENABLED=1 docker compose up -d --no-deps app
wait_healthy
docker compose ps
docker stats --no-stream > "$evidence/container-stats.txt"
docker compose exec -T app python - <<'PY'
import json
from pathlib import Path
from backend import news
r=json.loads(Path('/data/domestic-acceptance/result.json').read_text())
print(json.dumps({'source_counts':{key:value['stored'] for key,value in r['sources'].items()},
                  'blocked_sources':r['blocked_sources'],'categories':r['categories'],
                  'commercial_regions':r['commercial_regions'],'commercial_geography':r['commercial_geography'],
                  'container_recreation':r['container_recreation'],'backup_restore':r['isolated_backup_restore'],
                  'old_article_identities':r['v1_identity_preservation'],
                  'availability':[{k:row[k] for k in ('id','enabled','availability_note')} for row in news.sources_status() if row['id'] in ('spacex','blue_origin','skyroot')]},ensure_ascii=False,indent=2))
PY
echo "Batch $batch enabled-source acceptance passed; blocked companies remain unresolved. Evidence: $evidence"
