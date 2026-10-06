#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/space-news
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/reading-upgrade-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
old=$(docker compose ps -q app)
[[ -n "$old" && -f .env ]]
old_image=$(docker inspect "$old" --format '{{.Image}}')
old_volume=$(docker inspect "$old" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ -n "$old_volume" ]]
old_collect=$(docker inspect "$old" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^COLLECT_ENABLED=//p')
old_collect=${old_collect:-1}
printf '%s\n' "$old_image" > "$evidence/previous-image-id.txt"
printf '%s\n' "$old_volume" > "$evidence/previous-volume.txt"
cp -p .env "$evidence/env-backup"
chmod 600 "$evidence/env-backup"
wait_healthy() {
  for attempt in $(seq 1 60); do
    id=$(docker compose ps -q app)
    if [[ -n "$id" && $(docker inspect "$id" --format '{{.State.Health.Status}}') == healthy ]]; then return; fi
    sleep 2
  done
  return 1
}
rollback_image() {
  local status=$?
  trap - ERR
  echo "Upgrade failed ($status). Restoring previous image, keeping database and backup."
  docker compose logs --tail=60 app || true
  image_name=$(docker compose config --images | head -n 1)
  docker image tag "$old_image" "$image_name"
  COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --force-recreate --no-deps app || true
  echo "Evidence: $evidence"
  exit "$status"
}
trap rollback_image ERR
docker compose config --quiet
COLLECT_ENABLED=0 docker compose up -d --no-build --no-deps app
wait_healthy
docker compose exec -T app python - before < tools/accept_reading.py
paused=$(docker compose ps -q app)
docker cp "$paused:/data/reading-acceptance/before.sqlite3" "$evidence/before.sqlite3"
docker cp "$paused:/data/reading-acceptance/before.json" "$evidence/before.json"
docker compose build app
COLLECT_ENABLED=0 docker compose up -d --no-build --force-recreate --no-deps app
wait_healthy
docker compose run --rm --no-deps -e COLLECT_ENABLED=0 -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -v
docker compose exec -T app python -m tools.reading_manage import-missing /app/content/reading
docker compose exec -T app python -m tools.accept_reading capture
COLLECT_ENABLED=0 docker compose up -d --no-build --force-recreate --no-deps app
wait_healthy
docker compose exec -T app python -m tools.accept_reading after
new=$(docker compose ps -q app)
new_volume=$(docker inspect "$new" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ "$new_volume" == "$old_volume" && "$new" != "$old" ]]
COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --no-deps app
wait_healthy
docker compose exec -T app python -m tools.accept_reading after
final=$(docker compose ps -q app)
docker cp "$final:/data/reading-acceptance/result.json" "$evidence/result.json"
docker compose ps
docker stats --no-stream > "$evidence/container-stats.txt"
echo "Reading base checks passed. Check sample_acceptance in result.json and verify browser interaction. Evidence: $evidence"
