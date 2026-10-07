#!/usr/bin/env bash
# Deploy a reviewed Git snapshot; existing environment, keys and volume stay in place.
set -Eeuo pipefail
cd /opt/space-news
archive=${1:?release archive required}
checksum=${2:?SHA256 required}
revision=${3:?Git revision required}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
[[ "$checksum" =~ ^[0-9a-f]{64}$ ]]
test -f "$archive"
printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$PWD/unified-upgrade-$stamp"
mkdir -m 700 "$evidence"
mkdir "$evidence/stage" "$evidence/data-before"
exec > >(tee "$evidence/run.log") 2>&1
echo "Revision: $revision; backup: $evidence"
old_app=$(docker compose ps -q app)
old_admin=$(docker compose --profile review ps -q admin)
test -n "$old_app"
old_image=$(docker inspect "$old_app" --format '{{.Image}}')
image_name=$(docker inspect "$old_app" --format '{{.Config.Image}}')
old_admin_image=$old_image
if [[ -n "$old_admin" ]]; then old_admin_image=$(docker inspect "$old_admin" --format '{{.Image}}'); fi
printf '%s\n' "$old_image" > "$evidence/app-image.txt"
printf '%s\n' "$old_admin_image" > "$evidence/admin-image.txt"
docker inspect "$old_app" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' > "$evidence/data-volume.txt"
docker compose config --quiet
python3 - "$archive" "$evidence/stage" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path,PurePosixPath
root=Path(sys.argv[2])
with tarfile.open(sys.argv[1]) as tar:
    members=tar.getmembers()
    assert len(members)<2000
    for member in members:
        path=PurePosixPath(member.name)
        assert not path.is_absolute() and '..' not in path.parts
        assert member.isfile() or member.isdir()
        assert path.parts[0] in {'backend','web','admin_web','content','tools','tests','Dockerfile','requirements.txt','compose.yaml','release-manifest.json'}
        if member.isdir():continue
        assert member.size<10000000
        dest=root/member.name;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(tar.extractfile(member).read())
manifest=json.loads((root/'release-manifest.json').read_text())
for item in manifest['files']:
    assert hashlib.sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256']
print('Reviewed snapshot extracted:',manifest['revision'])
PY
# No configuration or key files are replaced or read into logs.
tar -czf "$evidence/source-before.tar.gz" backend web admin_web content tools tests Dockerfile requirements.txt compose.yaml
mutated=0
stopped=0
rollback() {
 local code=$?
 trap - ERR
 if [[ "$mutated" == 1 ]]; then
  echo 'Deployment failed; restoring previous code and image.'
  tar -xzf "$evidence/source-before.tar.gz" -C "$PWD" || true
  docker image tag "$old_image" "$image_name" || true
  docker compose --profile review up -d --no-build --force-recreate app ${old_admin:+admin} || true
 elif [[ "$stopped" == 1 ]]; then
  docker start "$old_app" ${old_admin:+$old_admin} || true
 fi
 echo "Deployment stopped (exit=$code); backup: $evidence"
 exit "$code"
}
trap rollback ERR
mutated=1
for directory in backend web admin_web content tools tests; do
 mkdir -p "$directory"
 cp -a "$evidence/stage/$directory/." "$directory/"
done
for file in Dockerfile requirements.txt compose.yaml; do cp "$evidence/stage/$file" "$file"; done
docker compose config --quiet
echo 'Building image while previous containers continue serving.'
docker compose build app
echo 'Stopping writers briefly for a consistent data snapshot.'
stopped=1
docker stop --time 75 "$old_app" ${old_admin:+$old_admin}
docker run --rm --volumes-from "$old_app" -v "$evidence/data-before:/backup" --user 0 --entrypoint python "$old_image" -c '
import sqlite3,shutil
from pathlib import Path
from contextlib import closing
base=Path("/data");target=Path("/backup")
for source in base.rglob("*"):
 if not source.is_file() or source.name.endswith(("-wal","-shm",".lock")):continue
 dest=target/source.relative_to(base);dest.parent.mkdir(parents=True,exist_ok=True)
 if source.suffix in (".sqlite3",".db"):
  with closing(sqlite3.connect(source)) as origin,closing(sqlite3.connect(dest)) as saved:origin.backup(saved)
 else:shutil.copy2(source,dest)
print("Persistent data snapshot complete")'
docker compose --profile review up -d --no-build --force-recreate app ${old_admin:+admin}
for attempt in $(seq 1 30); do
 app=$(docker compose ps -q app)
 status=$(docker inspect "$app" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
 admin_status=healthy
 if [[ -n "$old_admin" ]]; then
  admin=$(docker compose --profile review ps -q admin)
  admin_status=$(docker inspect "$admin" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
 fi
 if [[ "$status" == healthy && "$admin_status" == healthy ]]; then break; fi
 sleep 2
done
test "$status" = healthy
test "$admin_status" = healthy
test "$(docker inspect "$app" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')" = "$(cat "$evidence/data-volume.txt")"
docker cp "$evidence/stage/release-manifest.json" "$app:/tmp/release-manifest.json"
docker cp "$evidence/data-before/news.sqlite3" "$app:/tmp/news-before.sqlite3"
docker compose exec -T app python tools/verify_current_release.py
if [[ -n "$old_admin" ]]; then
 docker compose --profile review exec -T admin python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8001/health",timeout=10); print("Admin health HTTP",r.status)'
fi
printf '%s\n' "$revision" > "$evidence/deployed-revision.txt"
docker compose --profile review ps
echo "DEPLOYMENT_OK revision=$revision evidence=$evidence"
