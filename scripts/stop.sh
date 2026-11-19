#!/usr/bin/env bash
# Stop the dev servers started by ./scripts/dev.sh — idempotent, safe to run anytime.
#
#   ./scripts/stop.sh              # stop runs/dev/*.pid + :8000 backend + :5173 vite
#   ./scripts/stop.sh --status     # show ports, PID files, health and the PG tunnel
#   ./scripts/stop.sh --all        # also :8010 + :5174 (the Playwright honesty project)
#   ./scripts/stop.sh --tunnel     # also close the team04 PG tunnel
#   ./scripts/stop.sh --force      # kill whatever listens on the ports (not only uvicorn/vite)
#   PORT=8010 WEB_PORT=5174 ./scripts/stop.sh
#
# It prints what each PID/port belongs to before killing it. Nothing listening is normal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_DIR="$ROOT/runs/dev"
BACKEND_PID_FILE="$STATE_DIR/backend.pid"
WEB_PID_FILE="$STATE_DIR/web.pid"
META_FILE="$STATE_DIR/meta"
BACKEND_LOG="$STATE_DIR/backend.log"
WEB_LOG="$STATE_DIR/web.log"

PORTS=("${PORT:-8000}" "${WEB_PORT:-5173}")
ACTION=stop
FORCE=0
TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --all) PORTS+=("${HONEST_PORT:-8010}" 5174) ;;
    --tunnel) TUNNEL=1 ;;
    --status) ACTION=status ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

port_pids() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true; }
describe() { ps -p "$1" -o command= 2>/dev/null | cut -c1-90 || true; }
command_full() { ps -p "$1" -o command= 2>/dev/null || true; }
is_project_process() {
  printf '%s' "$1" | grep -Eq 'uvicorn app\.api\.main|node.*vite|vite'
}
tunnel_pids() {
  local port="${PG_TUNNEL_PORT:-15432}" pids pid cmd
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  for pid in $pids; do
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    case "$cmd" in
      *ssh*|*"ssh:"*) echo "$pid" ;;
    esac
  done
}

read_pid() {
  local file="$1" pid
  [ -f "$file" ] || return 0
  pid="$(tr -dc '0-9' <"$file")"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

status_line() {
  local label="$1" pid="$2" cmd
  if [ -z "$pid" ]; then
    echo "·  $label 未运行"
    return
  fi
  cmd="$(describe "$pid")"
  echo "→  $label pid $pid  ${cmd:-（进程已退出）}"
}

show_status() {
  echo "smart-edit dev status"
  echo "────────────────────────────────────────────────────────────"
  status_line "backend.pid" "$(read_pid "$BACKEND_PID_FILE")"
  status_line "web.pid    " "$(read_pid "$WEB_PID_FILE")"
  for port in "${PORTS[@]}"; do
    pids="$(port_pids "$port")"
    if [ -z "$pids" ]; then
      echo "·  :$port 未监听"
    else
      for pid in $pids; do
        echo "→  :$port pid $pid  $(describe "$pid")"
      done
    fi
  done
  health="$(curl -fsS "http://127.0.0.1:${PORT:-8000}/health" 2>/dev/null || true)"
  [ -n "$health" ] && echo "→  health: $health"
  if [ -n "$(tunnel_pids)" ]; then
    echo "→  PG tunnel :${PG_TUNNEL_PORT:-15432} open (pid $(tunnel_pids | tr '\n' ' '))"
  else
    echo "·  PG tunnel :${PG_TUNNEL_PORT:-15432} closed"
  fi
  [ -f "$META_FILE" ] && { echo "→  meta:"; sed 's/^/     /' "$META_FILE"; }
  echo "→  logs: $BACKEND_LOG"
  echo "          $WEB_LOG"
}

kill_pid() {
  local pid="$1" label="$2"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  kill -9 "$pid" 2>/dev/null || true
  echo "→  $label pid $pid 强制停止"
}

if [ "$ACTION" = status ]; then
  show_status
  exit 0
fi

stopped=0

# 1) PID files first: they point at the exact process, even if the port moved.
for pair in "$BACKEND_PID_FILE:backend" "$WEB_PID_FILE:web"; do
  file="${pair%%:*}"; label="${pair##*:}"
  pid="$(read_pid "$file")"
  if [ -n "$pid" ]; then
    cmd="$(describe "$pid")"
    full="$(command_full "$pid")"
    if [ "$FORCE" = 0 ] && ! is_project_process "$full"; then
      echo "·  $label pid $pid 不是本项目进程，跳过：$cmd" >&2
      continue
    fi
    echo "→ 停止 $label pid $pid  $cmd"
    kill_pid "$pid" "$label"
    stopped=$((stopped + 1))
  fi
  rm -f "$file"
done

# 2) Port fallback: catches a foreground `npm run dev` or a previously orphaned server.
for port in "${PORTS[@]}"; do
  pids="$(port_pids "$port")"
  if [ -z "$pids" ]; then
    continue
  fi
  for pid in $pids; do
    cmd="$(describe "$pid")"
    full="$(command_full "$pid")"
    if [ "$FORCE" = 0 ] && ! is_project_process "$full"; then
      echo "·  :$port pid $pid 不是本项目进程，跳过：$cmd" >&2
      continue
    fi
    echo "→ 停止 :$port pid $pid  $cmd"
    kill_pid "$pid" ": $port"
    stopped=$((stopped + 1))
  done
done

rm -f "$META_FILE"

if [ "$TUNNEL" = 1 ]; then
  pids="$(tunnel_pids)"
  if [ -n "$pids" ]; then
    echo "→ 关闭 PG 隧道 pid $pids"
    kill $pids 2>/dev/null || true
    stopped=$((stopped + 1))
  else
    echo "·  PG 隧道未运行"
  fi
fi

if [ "$stopped" -eq 0 ]; then
  echo "→ 没有需要停止的进程"
else
  echo "→ 已停止 $stopped 个进程/端口"
fi