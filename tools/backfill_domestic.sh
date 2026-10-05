#!/usr/bin/env bash
# Serial bounded batches, resumable across invocations. No full-archive startup crawl.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
source=${1:?Usage: bash tools/backfill_domestic.sh SOURCE [MAX_BATCHES=10]}
max_batches=${2:-10}
case "$source" in cnsa|cmse|cas_space|landspace) ;; *) echo "Unknown source"; exit 1 ;; esac
[[ "$max_batches" =~ ^[1-9][0-9]*$ ]]
folder="$PWD/backfill-evidence/$source"
mkdir -p "$folder"
run_id=''
[[ ! -f "$folder/run-id" ]] || run_id=$(cat "$folder/run-id")
for batch in $(seq 1 "$max_batches"); do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  output="$folder/$stamp.json"
  args=(--source "$source" --since 2025-10-01 --max-pages 5 --max-articles 50 --max-seconds 240)
  [[ -z "$run_id" ]] || args+=(--resume "$run_id")
  # Preserve a failed batch's JSON so it can still provide the checkpoint ID.
  code=0
  docker compose exec -T app python -m backend.backfill "${args[@]}" > "$output" || code=$?
  if [[ ! -s "$output" ]]; then
    echo "Command failed before checkpoint output; saved run ID is unchanged."
    exit 1
  fi
  status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$output")
  if [[ "$status" == paused_lock ]]; then
    echo "Collector is busy; retrying in 5 seconds."
    sleep 5
    continue
  fi
  run_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$output")
  printf '%s\n' "$run_id" > "$folder/run-id"
  echo "$source batch=$batch status=$status evidence=$output"
  case "$status" in
    enumerated_complete) echo "Public archive enumeration complete; read date coverage in JSON."; exit 0 ;;
    enumerated_with_gaps) echo "Archive enumerated with gaps; inspect failures/undated records before completion."; exit 2 ;;
    paused_error|paused_throttle) cat "$output"; exit 1 ;;
  esac
  [[ "$code" == 0 ]] || exit "$code"
done
echo "Batch budget reached. Repeat the same command to resume run $run_id."
