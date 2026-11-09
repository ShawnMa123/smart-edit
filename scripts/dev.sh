#!/usr/bin/env bash
# One-shot dev runner: backend (uvicorn) + frontend (vite), started and stopped together.
#
#   ./scripts/dev.sh              # backend :8000 with the recorded fixture model, UI :5173
#   ./scripts/dev.sh --honest     # backend :8000 with NO model provider (the "checks did not run" path)
#   PORT=8010 WEB_PORT=5174 ./scripts/dev.sh
#
# Ctrl+C stops both. Uses VITE_PROXY_TARGET so a non-default PORT still reaches the backend.
# Lost the terminal? ./scripts/stop.sh clears :$PORT and :$WEB_PORT (--all adds the E2E ports).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
FIXTURE="fixture:fixtures/llm/extract_sample.json"
HONEST=0
for arg in "$@"; do
  case "$arg" in
    --honest) HONEST=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

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

if [ "$HONEST" = 1 ]; then
  export SMART_EDIT_LLM=""
  echo "→ 模型 provider：未配置（诚实路径：字段检查不会运行）"
else
  export SMART_EDIT_LLM="${SMART_EDIT_LLM:-$FIXTURE}"
  echo "→ 模型 provider：${SMART_EDIT_LLM}"
fi

BACKEND_LOG="$(mktemp -t smart-edit-backend.XXXXXX.log)"
.venv/bin/uvicorn app.api.main:app --port "$PORT" --log-level warning >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

cleanup() {
  if [ -n "${VITE_PID:-}" ]; then
    kill "$VITE_PID" 2>/dev/null || true
    # npm 的子进程可能被孤儿化，按端口兜底（这是脚本自己打印的那个端口）。
    kill_port "$WEB_PORT"
  fi
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  echo
  echo "→ 已停止。后端日志：$BACKEND_LOG"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 等后端真的能应答，再起前端：否则前端一打开就是 ECONNREFUSED。
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/openapi.json" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "后端启动失败：" >&2; tail -20 "$BACKEND_LOG" >&2; exit 1
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:${PORT}/openapi.json" >/dev/null 2>&1 || {
  echo "后端 10 秒内未就绪：" >&2; tail -20 "${BACKEND_LOG}" >&2; exit 1;
}

echo "→ 后端 http://127.0.0.1:${PORT}   （日志 ${BACKEND_LOG}）"
echo "→ 前端 http://localhost:${WEB_PORT}"
echo "→ 粘贴内容取 fixtures/llm/sample_document.txt   （Ctrl+C 停止）"

# 前端与后端同生共死：前端在前台等待，EXIT/INT trap 负责收尾。
cd web
VITE_PROXY_TARGET="http://127.0.0.1:$PORT" npm run dev -- --port "$WEB_PORT" --strictPort &
VITE_PID=$!
wait "$VITE_PID"