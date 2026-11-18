#!/usr/bin/env bash
# One-shot dev runner: backend (uvicorn) + frontend (vite), started and stopped together.
#
#   ./scripts/dev.sh              # backend :8000, UI :5173, both logs in the terminal
#   ./scripts/dev.sh --honest     # backend :8000 with NO model provider (the "checks did not run" path)
#   PORT=8010 WEB_PORT=5174 ./scripts/dev.sh
#   SMART_EDIT_LOG_LEVEL=DEBUG ./scripts/dev.sh   # also print every GET/polling request
#
# Backend and frontend lines are prefixed [backend] / [web] and mirrored to runs/logs/*.log.
# Ctrl+C stops both. Uses VITE_PROXY_TARGET so a non-default PORT still reaches the backend.
# Lost the terminal? ./scripts/stop.sh clears :$PORT and :$WEB_PORT (--all adds the E2E ports).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Local overrides (gitignored): model provider keys, egress policy, ports…
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
  echo "→ 已加载 .env（本地配置，不入库）"
fi

PORT="${PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"
LOG_DIR="${LOG_DIR:-$ROOT/runs/logs}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKEND_LOG="$LOG_DIR/backend-$STAMP.log"
WEB_LOG="$LOG_DIR/web-$STAMP.log"
SMART_EDIT_LOG_LEVEL="${SMART_EDIT_LOG_LEVEL:-INFO}"
BACKEND_LOG_LEVEL="$(printf '%s' "${BACKEND_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
FIXTURE="fixture:fixtures/llm/extract_sample.json"
HONEST=0
for arg in "$@"; do
  case "$arg" in
    --honest) HONEST=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# Stream one process's output to the terminal and keep a copy on disk. `awk` flushes each line so
# the terminal never waits for a 4 KB buffer; `tee -a` is the durable copy.
stream_logs() {
  local prefix="$1" file="$2"
  awk -v p="$prefix" '{ print p " " $0; fflush(); }' | tee -a "$file"
}

# 端口清理：BSD/macOS 的 xargs 没有 -r，用 if 判断更稳。
kill_port() {
  local pids
  pids="$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -n "$pids" ]; then kill -9 $pids 2>/dev/null || true; fi
}

# 上一个会话残留的进程会给出 "unregistered stage target: audit" 这类假故障。
kill_port "$PORT"
kill_port "$WEB_PORT"

[ -x .venv/bin/uvicorn ] || { echo "缺少 .venv：先执行 python3 -m venv .venv && .venv/bin/pip install -e ." >&2; exit 1; }
[ -d web/node_modules ] || { echo "缺少 web/node_modules：先执行 npm --prefix web ci"; exit 1; }

mkdir -p "$LOG_DIR"
: > "$BACKEND_LOG"
: > "$WEB_LOG"
export SMART_EDIT_LOG_LEVEL BACKEND_LOG_LEVEL

if [ "$HONEST" = 1 ]; then
  export SMART_EDIT_LLM=""
  echo "→ 模型 provider：未配置（诚实路径：字段检查不会运行）"
else
  export SMART_EDIT_LLM="${SMART_EDIT_LLM:-$FIXTURE}"
  echo "→ 模型 provider：${SMART_EDIT_LLM}"
fi

echo
echo "════════════════════════════════════════════════════════════════"
echo " smart-edit dev"
echo "   backend : http://$HOST:$PORT   (uvicorn, log-level=$BACKEND_LOG_LEVEL)"
echo "   frontend: http://localhost:$WEB_PORT   (vite)"
echo "   database: ${SMART_EDIT_ASSISTANT_DB:-runs/assistant.db}"
echo "   model   : ${SMART_EDIT_ASSISTANT_MODEL:-fixture composer}"
echo "   web     : general_web=${SMART_EDIT_ASSISTANT_GENERAL_WEB:-0} approved_provider=${SMART_EDIT_ASSISTANT_WEB:-off}"
echo "   logs    : $BACKEND_LOG"
echo "             $WEB_LOG"
echo "   app log : SMART_EDIT_LOG_LEVEL=${SMART_EDIT_LOG_LEVEL}（DEBUG 可看到 GET/轮询）"
echo "════════════════════════════════════════════════════════════════"
echo

# Backend: stream to the terminal and keep a copy on disk. `--no-access-log` avoids a duplicate
# request line for every 500 ms poll; the app logger prints POST/PUT and errors itself.
(
  .venv/bin/uvicorn app.api.main:app \
    --host "$HOST" --port "$PORT" \
    --log-level "$BACKEND_LOG_LEVEL" \
    --no-use-colors --no-access-log 2>&1 \
    | stream_logs "[backend]" "$BACKEND_LOG"
) &
BACKEND_PID=$!

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  echo
  if [ -n "${VITE_PID:-}" ]; then
    kill "$VITE_PID" 2>/dev/null || true
    # npm 的子进程可能被孤儿化，按端口兜底（这是脚本自己打印的那个端口）。
    kill_port "$WEB_PORT"
  fi
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    kill_port "$PORT"
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  echo "→ 已停止"
  echo "  后端日志: $BACKEND_LOG"
  echo "  前端日志: $WEB_LOG"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 等后端真的能应答，再起前端：否则前端一打开就是 ECONNREFUSED。
READY=0
for _ in $(seq 1 80); do
  if curl -fsS "http://$HOST:$PORT/openapi.json" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then break; fi
  sleep 0.25
done
if [ "$READY" != 1 ]; then
  echo "后端启动失败（最近日志）：" >&2
  tail -n 30 "$BACKEND_LOG" >&2 || true
  exit 1
fi

echo "→ backend ready: http://$HOST:$PORT"
echo "→ API docs:      http://$HOST:$PORT/docs"
curl -fsS "http://$HOST:$PORT/assistant/capabilities" -H 'X-Demo-User: user_demo_01' 2>/dev/null \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
m, l, e, w = d["model"], d["layers"], d["egress"], d["web"]
print("→ model      : %s | configured=%s approved=%s" % (m["label"] or "fixture", m["configured"], m["approved_processor"]))
print("→ layers     : local=%s approved_web=%s general_web=%s" % (l["local"], l["approved_web"], l["general_web"]))
print("→ egress     : policy=%s domains=%s loaded=%s" % (e["policy_version"], e["allowed_domains"], e["loaded"]))
print("→ web        : provider=%s" % w["provider"])
' || echo "→ capabilities 查询失败（看 $BACKEND_LOG）"

echo
echo "→ frontend starting: http://localhost:$WEB_PORT   （Ctrl+C 停止）"
# 前端与后端同生共死：前端在前台等待，EXIT/INT trap 负责收尾。
cd "$ROOT/web"
VITE_PROXY_TARGET="http://$HOST:$PORT" NO_COLOR=1 FORCE_COLOR=0 \
  npm run dev -- --port "$WEB_PORT" --strictPort 2>&1 \
  | stream_logs "[web]" "$WEB_LOG" &
VITE_PID=$!
wait "$VITE_PID"