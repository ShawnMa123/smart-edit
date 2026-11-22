#!/usr/bin/env bash
# One-shot dev runner: backend (uvicorn) + frontend (vite), started and stopped together.
#
#   ./scripts/dev.sh                     # fake identity, backend :8000, UI :5173, logs in this terminal
#   ./scripts/dev.sh --pg                # PG identity (auth_mode=pg), checks/starts the team04 tunnel
#   ./scripts/dev.sh --pg --detach       # run in background, print URLs and the stop command
#   ./scripts/dev.sh --pg --detach --open
#   ./scripts/dev.sh --honest            # same as the default: no model provider
#   ./scripts/dev.sh --fixture           # OPT-IN replay: every document returns the sample guarantee
#   PORT=8010 WEB_PORT=5174 ./scripts/dev.sh
#   ./scripts/dev.sh --status            # show ports/PIDs/PG tunnel (same as stop.sh --status)
#
# Flags:
#   --pg | --fake        identity mode (default: SMART_EDIT_AUTH_MODE or fake)
#   --detach, -d         background; PIDs go to runs/dev/*.pid
#   --open               open the UI in the browser when ready
#   --force              free a port even when the owner is not uvicorn/vite
#   --no-tunnel          never start the PG tunnel automatically (fail if it is closed)
#   --honest             clear SMART_EDIT_LLM (now the default)
#   --fixture            replay fixtures/llm/extract_sample.json (demo only; ignores the document)
#   --status             print status and exit
#
# Backend/frontend logs: runs/dev/backend.log and runs/dev/web.log (stable paths).
# Stop with ./scripts/stop.sh, or ./scripts/stop.sh --tunnel to also close the PG tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() { sed -n '2,24p' "$0"; }
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
done

# Capture explicit env values before sourcing .env, so `PORT=… ./scripts/dev.sh` wins.
PRESET_PORT="${PORT:-}"
PRESET_WEB_PORT="${WEB_PORT:-}"
PRESET_HOST="${HOST:-}"
PRESET_AUTH="${SMART_EDIT_AUTH_MODE:-}"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
  echo "→ 已加载 .env（本地配置，不入库）"
fi

[ -n "$PRESET_PORT" ] && PORT="$PRESET_PORT"
[ -n "$PRESET_WEB_PORT" ] && WEB_PORT="$PRESET_WEB_PORT"
[ -n "$PRESET_HOST" ] && HOST="$PRESET_HOST"

PORT="${PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"
LOG_DIR="${LOG_DIR:-$ROOT/runs/dev}"
STATE_DIR="$ROOT/runs/dev"
BACKEND_LOG="$LOG_DIR/backend.log"
WEB_LOG="$LOG_DIR/web.log"
BACKEND_PID_FILE="$STATE_DIR/backend.pid"
WEB_PID_FILE="$STATE_DIR/web.pid"
META_FILE="$STATE_DIR/meta"
SMART_EDIT_LOG_LEVEL="${SMART_EDIT_LOG_LEVEL:-INFO}"
BACKEND_LOG_LEVEL="$(printf '%s' "${BACKEND_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
FIXTURE="fixture:fixtures/llm/extract_sample.json"
PG_TUNNEL_HOST="${PG_TUNNEL_HOST:-team04-pg}"

HONEST=0
FIXTURE_REPLAY=0
DETACH=0
OPEN_UI=0
FORCE=0
TUNNEL=1
ACTION=run
AUTH_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --pg) AUTH_FLAG="pg" ;;
    --fake) AUTH_FLAG="fake" ;;
    --detach|-d) DETACH=1 ;;
    --open) OPEN_UI=1 ;;
    --force) FORCE=1 ;;
    --no-tunnel) TUNNEL=0 ;;
    --honest) HONEST=1 ;;
    --fixture) FIXTURE_REPLAY=1 ;;
    --status) ACTION=status ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ "$ACTION" = status ]; then
  PORT="$PORT" WEB_PORT="$WEB_PORT" exec "$ROOT/scripts/stop.sh" --status
fi

AUTH_MODE="${AUTH_FLAG:-${PRESET_AUTH:-${SMART_EDIT_AUTH_MODE:-fake}}}"
case "$AUTH_MODE" in
  fake|pg) ;;
  *) echo "SMART_EDIT_AUTH_MODE must be fake or pg; got '$AUTH_MODE'" >&2; exit 2 ;;
esac
export SMART_EDIT_AUTH_MODE="$AUTH_MODE"

mkdir -p "$LOG_DIR" "$STATE_DIR"
: > "$BACKEND_LOG"
: > "$WEB_LOG"
port_pids() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true; }
describe() { ps -p "$1" -o command= 2>/dev/null | cut -c1-90 || true; }
command_full() { ps -p "$1" -o command= 2>/dev/null || true; }

free_port() {
  local port="$1" pids pid cmd full
  pids="$(port_pids "$port")"
  [ -z "$pids" ] && return 0
  for pid in $pids; do
    cmd="$(describe "$pid")"
    full="$(command_full "$pid")"
    if [ "$FORCE" = 0 ] && ! printf '%s' "$full" | grep -Eq 'uvicorn app\.api\.main|node.*vite|vite'; then
      echo "端口 :$port 被非本项目进程占用：pid $pid $cmd" >&2
      echo "确认可以停止它之后，重新运行并加 --force" >&2
      exit 1
    fi
    echo "→ 释放 :$port pid $pid ($cmd)"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
  done
}

url_target() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
print(f"{u.hostname or 'localhost'} {u.port or 5432} {u.path.lstrip('/') or 'postgres'}")
PY
}

ensure_pg() {
  local url="${SMART_EDIT_DATABASE_URL:-}" host port dbname
  if [ -z "$url" ]; then
    echo "AUTH_MODE=pg 但未配置 SMART_EDIT_DATABASE_URL（.env 或环境变量）" >&2
    exit 1
  fi
  IFS=' ' read -r host port dbname < <(url_target "$url")
  echo "→ 身份模式：pg   target=${host}:${port}/${dbname}"
  if [ "$host" = "127.0.0.1" ] || [ "$host" = "localhost" ]; then
    if ! nc -z "$host" "$port" 2>/dev/null; then
      if [ "$TUNNEL" = 1 ]; then
        echo "→ PG 未监听，尝试启动隧道：ssh -f -N ${PG_TUNNEL_HOST}"
        ssh -o BatchMode=yes -o ConnectTimeout=8 -f -N "$PG_TUNNEL_HOST" 2>/dev/null || true
        sleep 1
      fi
      if ! nc -z "$host" "$port" 2>/dev/null; then
        echo "PG 端口 $host:$port 不可达。" >&2
        echo "先执行 ssh -f -N ${PG_TUNNEL_HOST}，或改用 ./scripts/dev.sh --fake" >&2
        exit 1
      fi
      echo "→ PG 隧道已就绪：$host:$port"
    fi
  fi
}

free_port "$PORT"
free_port "$WEB_PORT"

[ -x .venv/bin/uvicorn ] || { echo "缺少 .venv：先执行 python3 -m venv .venv && .venv/bin/python -m pip install -e ." >&2; exit 1; }
[ -x web/node_modules/.bin/vite ] || { echo "缺少 web/node_modules：先执行 npm --prefix web ci" >&2; exit 1; }

export SMART_EDIT_LOG_LEVEL BACKEND_LOG_LEVEL
if [ "$AUTH_MODE" = "pg" ]; then
  ensure_pg
else
  echo "→ 身份模式：fake（X-Demo-User，仅本地演示）"
fi

if [ "$FIXTURE_REPLAY" = 1 ]; then
  export SMART_EDIT_LLM="$FIXTURE"
  echo "→ 模型 provider：${SMART_EDIT_LLM}（fixture 回放：任何文本都会返回同一份样例保函，仅用于演示）"
elif [ "$HONEST" = 1 ] || [ -z "${SMART_EDIT_LLM:-}" ]; then
  export SMART_EDIT_LLM=""
  echo "→ 模型 provider：未配置（模板一致性审计走 config 的确定性抽取档；/runs 的 extract 不会伪造字段）"
else
  echo "→ 模型 provider：${SMART_EDIT_LLM}（来自环境变量/.env）"
fi
stream_logs() {
  local prefix="$1"
  awk -v p="$prefix" '{ print p " " $0; fflush(); }'
}

BACKEND_PID=""
WEB_PID=""

start_backend() {
  local cmd=(.venv/bin/uvicorn app.api.main:app
    --host "$HOST" --port "$PORT"
    --log-level "$BACKEND_LOG_LEVEL" --no-use-colors --no-access-log)
  if [ "$DETACH" = 1 ]; then
    nohup "${cmd[@]}" >"$BACKEND_LOG" 2>&1 </dev/null &
  else
    "${cmd[@]}" > >(stream_logs "[backend]" | tee -a "$BACKEND_LOG") 2>&1 &
  fi
  BACKEND_PID=$!
  echo "$BACKEND_PID" >"$BACKEND_PID_FILE"
}

start_web() {
  if [ "$DETACH" = 1 ]; then
    (
      cd "$ROOT/web"
      exec env VITE_PROXY_TARGET="http://$HOST:$PORT" NO_COLOR=1 FORCE_COLOR=0 \
        "$ROOT/web/node_modules/.bin/vite" --port "$WEB_PORT" --strictPort
    ) >"$WEB_LOG" 2>&1 </dev/null &
  else
    (
      cd "$ROOT/web"
      exec env VITE_PROXY_TARGET="http://$HOST:$PORT" NO_COLOR=1 FORCE_COLOR=0 \
        "$ROOT/web/node_modules/.bin/vite" --port "$WEB_PORT" --strictPort
    ) > >(stream_logs "[web]" | tee -a "$WEB_LOG") 2>&1 &
  fi
  WEB_PID=$!
  echo "$WEB_PID" >"$WEB_PID_FILE"
}

stop_started() {
  local pid alive
  for pid in "${WEB_PID:-}" "${BACKEND_PID:-}"; do
    [ -n "$pid" ] || continue
    kill "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 30); do
    alive=0
    for pid in "${WEB_PID:-}" "${BACKEND_PID:-}"; do
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        alive=1
      fi
    done
    [ "$alive" = 0 ] && break
    sleep 0.1
  done
  for pid in "${WEB_PID:-}" "${BACKEND_PID:-}"; do
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
  done
  rm -f "$BACKEND_PID_FILE" "$WEB_PID_FILE" "$META_FILE"
}

wait_backend() {
  for _ in $(seq 1 160); do
    curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1 && return 0
    [ -n "${BACKEND_PID:-}" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null && return 1
    sleep 0.25
  done
  return 1
}

wait_web() {
  for _ in $(seq 1 120); do
    curl -fsS "http://localhost:$WEB_PORT/" >/dev/null 2>&1 && return 0
    [ -n "${WEB_PID:-}" ] && ! kill -0 "$WEB_PID" 2>/dev/null && return 1
    sleep 0.25
  done
  return 1
}

start_backend
if ! wait_backend; then
  echo "后端启动失败（最近日志）：" >&2
  tail -n 40 "$BACKEND_LOG" >&2 || true
  stop_started
  exit 1
fi

start_web
if ! wait_web; then
  echo "前端启动失败（最近日志）：" >&2
  tail -n 40 "$WEB_LOG" >&2 || true
  tail -n 20 "$BACKEND_LOG" >&2 || true
  stop_started
  exit 1
fi

cat >"$META_FILE" <<EOF
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
auth_mode=$AUTH_MODE
backend=http://$HOST:$PORT
web=http://localhost:$WEB_PORT
backend_pid=$BACKEND_PID
web_pid=$WEB_PID
backend_log=$BACKEND_LOG
web_log=$WEB_LOG
EOF

echo
echo "════════════════════════════════════════════════════════════════"
echo " smart-edit dev ready  ($([ "$DETACH" = 1 ] && echo background || echo foreground))"
echo "   identity : $AUTH_MODE"
echo "   frontend : http://localhost:$WEB_PORT"
echo "   backend  : http://$HOST:$PORT   (docs: /docs)"
echo "   logs     : $BACKEND_LOG"
echo "              $WEB_LOG"
echo "   stop     : ./scripts/stop.sh"
[ "$AUTH_MODE" = "pg" ] && echo "              ./scripts/stop.sh --tunnel   # 同时关闭 PG 隧道"
echo "════════════════════════════════════════════════════════════════"
echo

[ "$OPEN_UI" = 1 ] && open "http://localhost:$WEB_PORT" 2>/dev/null || true

if [ "$DETACH" = 1 ]; then
  echo "后台运行中。查看日志： tail -f $BACKEND_LOG $WEB_LOG"
  exit 0
fi

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  echo
  echo "→ 正在停止 dev 服务…"
  stop_started
  echo "→ 已停止"
  echo "  后端日志: $BACKEND_LOG"
  echo "  前端日志: $WEB_LOG"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "→ 前台运行中（Ctrl+C 停止）"
wait "$WEB_PID"
rm -f "$BACKEND_PID_FILE" "$WEB_PID_FILE"