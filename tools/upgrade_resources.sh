#!/usr/bin/env bash
# Run only in the existing deployment. No OSS checks or news-source probes.
set -Eeuo pipefail
cd /opt/space-news
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/resources-upgrade-$stamp"
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
# Preserve the old runtime settings for image rollback; never print the env file.
docker compose exec -T app python - before < tools/accept_resources.py
docker cp "$old:/data/resource-acceptance/before.sqlite3" "$evidence/before.sqlite3"
docker cp "$old:/data/resource-acceptance/before.json" "$evidence/before.json"
docker compose config --quiet
docker compose build app

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
  echo "Upgrade failed (status=$status). Restoring old image; retaining current database."
  docker compose logs --tail=80 app || true
  image_name=$(docker compose config --images | head -n 1)
  docker image tag "$old_image" "$image_name"
  COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --force-recreate --no-deps app || true
  echo "Evidence: $evidence. Code archive made before extraction remains in /root."
  exit "$status"
}
trap rollback_image ERR
COLLECT_ENABLED=0 docker compose up -d --no-build --no-deps app
wait_healthy
docker compose run --rm --no-deps -e COLLECT_ENABLED=0 -v "$PWD/tests:/app/tests:ro" app python -m unittest discover -s tests -v
docker compose exec -T app python -m tools.accept_resources after
new=$(docker compose ps -q app)
new_volume=$(docker inspect "$new" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ "$new" != "$old" && "$new_volume" == "$old_volume" ]]
docker cp "$new:/data/resource-acceptance/result.json" "$evidence/result.json"
COLLECT_ENABLED="$old_collect" docker compose up -d --no-build --no-deps app
wait_healthy
docker compose exec -T app python -m tools.accept_resources after
final=$(docker compose ps -q app)
final_volume=$(docker inspect "$final" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ "$final_volume" == "$old_volume" ]]
docker cp "$final:/data/resource-acceptance/result.json" "$evidence/result.json"
printf 'old_container=%s\nnew_container=%s\nvolume=%s\nscheduler=%s\n' "$old" "$final" "$final_volume" "$old_collect" > "$evidence/containers.txt"
docker compose ps
docker stats --no-stream > "$evidence/container-stats.txt"
cat "$evidence/result.json"
echo "Resource upgrade checks passed. Evidence: $evidence"
