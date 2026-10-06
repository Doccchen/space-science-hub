#!/usr/bin/env bash
# Run manually on the existing server. Does not change application settings or restart services.
set +x
set -Eeuo pipefail
umask 077
limit=${1:-1}
[[ "$limit" == 1 || "$limit" == 4 ]] || { echo 'Usage: bash /root/run_bailian_probe.sh [1|4]'; exit 2; }
cd /opt/space-news
container=$(docker compose ps -q app)
test -n "$container"
test -f /root/probe_bailian.py
work=/root/bailian-probe-work
mkdir -p "$work"
chmod 700 "$work"
if [[ ! -f "$work/questions.json" ]]; then
  python3 /root/probe_bailian.py --prepare "$work/questions.json"
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
remote="/tmp/bailian-probe-$stamp"
docker exec -u 0 "$container" mkdir -m 700 "$remote"
docker cp /root/probe_bailian.py "$container:$remote/probe_bailian.py"
docker cp "$work/questions.json" "$container:$remote/questions.json"
echo "最多发起 $limit 次真实调用；不会自动重试，可能产生百炼费用。"
if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  read -r -s -p '粘贴百炼 API Key（输入不显示）：' DASHSCOPE_API_KEY
  printf '\n'
fi
test -n "$DASHSCOPE_API_KEY"
export DASHSCOPE_API_KEY
export BAILIAN_WORKSPACE_ID="${BAILIAN_WORKSPACE_ID:-llm-ep9bqc9mnw50k8e0}"
export BAILIAN_AGENT_ID="${BAILIAN_AGENT_ID:-aid-066ddd0b6e1e44d6bf7d620e0ac7c060}"
trap 'unset DASHSCOPE_API_KEY' EXIT
set +e
docker compose exec -T -u 0 -e DASHSCOPE_API_KEY -e BAILIAN_WORKSPACE_ID -e BAILIAN_AGENT_ID app \
  python "$remote/probe_bailian.py" --live --questions "$remote/questions.json" \
  --output "$remote/results" --max-requests "$limit" --timeout 60
status=$?
set -e
unset DASHSCOPE_API_KEY
result="$work/results-$stamp"
mkdir -m 700 "$result"
if docker cp "$container:$remote/results/." "$result/"; then
  echo "结果保存在 $result"
  echo '可发回 summary.json；*-private.json 含问题/答案/检索片段，仅留服务器人工核对。'
  if [[ -f "$result/summary.json" ]]; then cat "$result/summary.json"; fi
else
  echo '尚无结果文件。检查配置与上方错误；不要发送 API Key。'
fi
exit "$status"
