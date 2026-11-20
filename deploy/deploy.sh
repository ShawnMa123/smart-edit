#!/usr/bin/env bash
# 一键部署 smart-edit 到阿里云 ECS，并把控制台发布在 http://<公网IP>:8082
#
#   ./deploy/deploy.sh                  # 构建前端 + 上传 + 远端安装/重启
#   ./deploy/deploy.sh --no-build       # 复用已有 web/dist
#   ./deploy/deploy.sh --seed-users     # 首次部署时写入 README 里的演示账号（会重置这些账号密码）
#   ./deploy/deploy.sh --remote-only    # 只重跑远端安装（改过 nginx/systemd 配置时）
#
# 环境变量（都有默认值，可覆盖）：
#   ECS_HOST=root@59.110.213.187   SSH_KEY=~/.ssh/team04_ecs
#   REMOTE_DIR=/opt/smart-edit     PUBLIC_URL=http://59.110.213.187:8082
#   ENV_FILE=deploy/env.ecs        PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
#
# 前置条件：deploy/env.ecs 存在（从 deploy/env.ecs.example 复制并填好数据库/模型密钥）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ECS_HOST="${ECS_HOST:-root@59.110.213.187}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/team04_ecs}"
REMOTE_DIR="${REMOTE_DIR:-/opt/smart-edit}"
PUBLIC_URL="${PUBLIC_URL:-http://59.110.213.187:8082}"
ENV_FILE="${ENV_FILE:-$ROOT/deploy/env.ecs}"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"

BUILD=1
SEED_USERS=0
REMOTE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    --seed-users) SEED_USERS=1 ;;
    --remote-only) REMOTE_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

[ -f "$ENV_FILE" ] || {
  echo "缺少 $ENV_FILE" >&2
  echo "先执行：cp deploy/env.ecs.example deploy/env.ecs，再填好 SMART_EDIT_DATABASE_URL / API key。" >&2
  exit 2
}
[ -f "$SSH_KEY" ] || { echo "SSH key 不存在：${SSH_KEY}（用 SSH_KEY=... 指定）" >&2; exit 2; }

SSH=(ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
RSYNC_RSH="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

echo "== 0/5 检查 SSH：$ECS_HOST"
"${SSH[@]}" "$ECS_HOST" 'echo "  connected: $(hostname) $(python3 --version)"'

if [ "$REMOTE_ONLY" = 0 ]; then
  if [ "$BUILD" = 1 ]; then
    echo "== 1/5 构建前端（web/dist）"
    npm --prefix web run build
  else
    echo "== 1/5 跳过构建（--no-build）"
  fi
  [ -f web/dist/index.html ] || { echo "web/dist 不存在，去掉 --no-build 重新构建" >&2; exit 2; }

  echo "== 2/5 同步代码到 $ECS_HOST:${REMOTE_DIR}（不含 .venv / node_modules / runs / 本地 .env）"
  "${SSH[@]}" "$ECS_HOST" "mkdir -p '$REMOTE_DIR'"
  rsync -az --delete \
    -e "$RSYNC_RSH" \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude 'web/node_modules/' \
    --exclude 'web/test-results/' \
    --exclude 'runs/' \
    --exclude 'data/' \
    --exclude '.env' \
    --exclude 'deploy/env.ecs' \
    --exclude 'tradeAI_requirementDesign_v2/' \
    --exclude 'docs/' \
    --exclude '.cline/' \
    --exclude '.clinerules/' \
    --exclude '.pytest_cache/' \
    --exclude '*.egg-info/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    ./ "$ECS_HOST:$REMOTE_DIR/"

  echo "== 3/5 上传运行时环境变量（/opt/smart-edit/.env, 600）"
  rsync -az -e "$RSYNC_RSH" --chmod=u=rw,go= "$ENV_FILE" "$ECS_HOST:$REMOTE_DIR/.env"
else
  echo "== 1-3/5 跳过构建与同步（--remote-only）"
fi

echo "== 4/5 远端安装并重启（pip / systemd / nginx）"
"${SSH[@]}" "$ECS_HOST" "cd '$REMOTE_DIR' && APP_DIR='$REMOTE_DIR' PIP_INDEX='$PIP_INDEX' SEED_USERS='$SEED_USERS' bash deploy/remote-setup.sh"

echo "== 5/5 外网可达性"
code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$PUBLIC_URL/health" || true)"
echo "  $PUBLIC_URL/health -> HTTP ${code:-000}"
if [ "$code" != "200" ]; then
  cat <<EOF

外网访问不通。服务器本机已通过（deploy/remote-setup.sh 的那一步），请检查：
  1) 阿里云控制台 → 该实例 → 安全组 → 入方向是否放行 TCP 8082（来源 0.0.0.0/0）；
  2) 服务器上：ss -lntp | grep 8082、systemctl status nginx。

EOF
  exit 1
fi

cat <<EOF

部署完成 🎉
  控制台：$PUBLIC_URL/
  健康检查：$PUBLIC_URL/health

常用命令（在 ECS 上）：
  journalctl -u smart-edit -f          # 后端日志
  systemctl restart smart-edit         # 重启后端
  tail -f /var/log/nginx/smart-edit.error.log

EOF