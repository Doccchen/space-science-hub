#!/usr/bin/env bash
set -Eeuo pipefail
cd /root
sha256sum -c space-nasa-credits-20261007.sha256
cd /opt/space-news
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$PWD/nasa-credit-upgrade-$stamp"
mkdir -m 700 "$backup"
mkdir "$backup/stage"
old_app=$(docker compose ps -q app)
test -n "$old_app"
old_image=$(docker inspect "$old_app" --format '{{.Image}}')
old_admin=$(docker compose --profile review ps -q admin)
tar -czf "$backup/source-before.tar.gz" backend/news_thumbnails.py
printf '%s\n' "$old_image" > "$backup/image-before.txt"
python3 - "$backup/stage" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
allowed={'backend/news_thumbnails.py','tests/test_news_thumbnails.py','docs/deployment/NASA历史配图署名修复-20261007.md','nasa-credits-manifest.json'}
with tarfile.open('/root/space-nasa-credits-20261007.tar.gz') as tar:
    members=tar.getmembers()
    assert len(members)==len(allowed) and {m.name for m in members}==allowed
    assert all(m.isfile() and m.size<500000 for m in members)
    files={m.name:tar.extractfile(m).read() for m in members}
manifest=json.loads(files['nasa-credits-manifest.json'])
assert {item['path'] for item in manifest['files']}==allowed-{'nasa-credits-manifest.json'}
for item in manifest['files']:
    assert hashlib.sha256(files[item['path']]).hexdigest()==item['sha256']
for name,data in files.items():
    target=Path(sys.argv[1])/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
print('NASA credit patch validated')
PY
mutated=0
rollback(){
 code=$?;trap - ERR
 if [[ "$mutated" == 1 ]];then
  tar -xzf "$backup/source-before.tar.gz" -C /opt/space-news || true
  docker image tag "$old_image" space-news-app || true
  docker compose --profile review up -d --no-build --force-recreate app ${old_admin:+admin} || true
 fi
 echo "Update failed (exit=$code); backup: $backup" >&2;exit "$code"
}
trap rollback ERR
mutated=1
install -m 644 "$backup/stage/backend/news_thumbnails.py" backend/news_thumbnails.py
docker compose build app
docker compose --profile review up -d --no-build --force-recreate app ${old_admin:+admin}
for attempt in $(seq 1 30);do
 app=$(docker compose ps -q app)
 status=$(docker inspect "$app" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
 admin_status=healthy
 if [[ -n "$old_admin" ]];then
  admin=$(docker compose --profile review ps -q admin)
  admin_status=$(docker inspect "$admin" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
 fi
 if [[ "$status" == healthy && "$admin_status" == healthy ]];then break;fi
 sleep 2
done
test "$status" = healthy
test "$admin_status" = healthy
docker compose --profile review ps
echo "NASA_CREDIT_PATCH_OK backup=$backup"
