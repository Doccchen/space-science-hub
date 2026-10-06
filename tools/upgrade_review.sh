#!/usr/bin/env bash
# Pause both writers, preserve DB and local files together, then upgrade.
set -Eeuo pipefail
cd /opt/space-news
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/review-upgrade-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
old=$(docker compose ps -q app)
[[ -n "$old" ]]
old_image=$(docker inspect "$old" --format '{{.Image}}')
old_collect=$(docker inspect "$old" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^COLLECT_ENABLED=//p')
old_collect=${old_collect:-1}
old_admin=$(docker compose --profile review ps -q admin || true)
admin_running=false
if [[ -n "$old_admin" && $(docker inspect "$old_admin" --format '{{.State.Running}}') == true ]]; then admin_running=true; fi
wait_app() {
  for attempt in $(seq 1 60); do
    id=$(docker compose ps -q app)
    if [[ -n "$id" && $(docker inspect "$id" --format '{{.State.Health.Status}}') == healthy ]]; then return; fi
    sleep 2
  done
  return 1
}
restore_runtime() {
  local status=$?
  trap - ERR
  echo "Review upgrade failed ($status); restoring old image/runtime, retaining database and picture snapshot."
  image_name=$(docker compose config --images | head -n 1)
  docker image tag "$old_image" "$image_name"
  COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --force-recreate --no-deps app || true
  if [[ "$admin_running" == true ]]; then docker compose --profile review up -d --force-recreate --no-deps admin || true; fi
  echo "Evidence: $evidence"
  exit "$status"
}
trap restore_runtime ERR
docker compose --profile review stop admin
COLLECT_ENABLED=0 docker compose up -d --no-build --no-deps app
wait_app
docker compose exec -T app python - backup "/data/review-backups/$stamp" < tools/backup_review.py
paused=$(docker compose ps -q app)
docker cp "$paused:/data/review-backups/$stamp" "$evidence/joint-before"
bash tools/upgrade_reading.sh
COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --no-deps app
wait_app
if [[ "$admin_running" == true ]]; then docker compose --profile review up -d --force-recreate --no-deps admin; fi
docker compose --profile review ps
echo "Review code and base checks passed. Initialize/login administrator and perform browser/source-picture checks. Evidence: $evidence"
