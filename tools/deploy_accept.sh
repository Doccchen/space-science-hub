#!/usr/bin/env bash
# Execute from /opt/space-news after extracting the reviewed release package.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/acceptance-$stamp"
mkdir -p "$evidence"
exec > >(tee "$evidence/run.log") 2>&1
trap 'echo "FAILED at line $LINENO; see evidence directory"; docker compose logs --tail=100 app || true' ERR

if [[ ! -f .env ]]; then
  cat > .env <<'ENV'
BIND_ADDRESS=127.0.0.1
WEB_PORT=8080
COLLECT_INTERVAL_SECONDS=3600
PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV
fi
docker compose config --quiet
# Back up an existing running instance before making changes.
existing=$(docker compose ps -q app)
if [[ -n "$existing" ]]; then
  backup="/data/pre-deploy-$stamp.sqlite3"
  docker compose exec -T app python -c "import sqlite3; a=sqlite3.connect('/data/news.sqlite3'); b=sqlite3.connect('$backup'); a.backup(b); b.close(); a.close()"
  docker cp "$existing:$backup" "$evidence/pre-deploy.sqlite3"
fi
docker compose up -d --build
wait_ready() {
  for attempt in $(seq 1 60); do
    if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"; then
      return
    fi
    sleep 2
  done
  return 1
}
wait_ready
docker compose exec -T app python - before < tools/accept_news.py
old_container=$(docker compose ps -q app)
old_volume=$(docker inspect "$old_container" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ -n "$old_volume" ]]
docker compose up -d --force-recreate --no-deps app
wait_ready
new_container=$(docker compose ps -q app)
new_volume=$(docker inspect "$new_container" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
[[ "$old_container" != "$new_container" && "$old_volume" == "$new_volume" ]]
docker compose exec -T app python - after < tools/accept_news.py
docker cp "$new_container:/data/acceptance/result.json" "$evidence/result.json"
printf 'old_container=%s\nnew_container=%s\nvolume=%s\n' "$old_container" "$new_container" "$new_volume" > "$evidence/containers.txt"
docker compose ps
docker compose logs --tail=100 app > "$evidence/app.log"
echo "Server checks passed. Evidence: $evidence. Browser interaction still requires verification."
