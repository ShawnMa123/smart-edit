#!/usr/bin/env bash
# Stop the dev servers started by ./scripts/dev.sh — idempotent, safe to run anytime.
#
#   ./scripts/stop.sh          # :8000 (backend) + :5173 (vite)
#   ./scripts/stop.sh --all    # also :8010 + :5174 (the Playwright honesty project)
#   PORT=8010 WEB_PORT=5174 ./scripts/stop.sh
#
# It prints what each port belongs to before killing it, so you can see you are not stopping an
# unrelated service. Nothing listening on any port is a normal outcome, not an error.
set -euo pipefail

PORTS=("${PORT:-8000}" "${WEB_PORT:-5173}")
for arg in "$@"; do
  case "$arg" in
    --all) PORTS+=("${HONEST_PORT:-8010}" 5174) ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

describe() {
  # Short command line, so the operator can recognise what is about to die.
  ps -p "$1" -o command= 2>/dev/null | cut -c1-72
}

stopped=0
for port in "${PORTS[@]}"; do
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    echo "·  :$port  未监听"
    continue
  fi
  for pid in $pids; do
    echo "→ :$port  pid $pid  $(describe "$pid")"
  done
  kill $pids 2>/dev/null || true
  # 给 3 秒优雅退出，仍活着就 -9（SIGTERM 不一定能让 uvicorn 立刻放手）。
  for _ in $(seq 1 30); do
    kill -0 $pids 2>/dev/null || break
    sleep 0.1
  done
  kill -9 $pids 2>/dev/null || true
  stopped=$((stopped + 1))
done

if [ "$stopped" -eq 0 ]; then
  echo "→ 没有需要停止的进程"
else
  echo "→ 已清空 $stopped 个端口"
fi