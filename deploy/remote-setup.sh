#!/usr/bin/env bash
# 远端安装/更新：在 ECS 上以 root 执行（由 deploy/deploy.sh 调用，也可手动跑）。
#
#   bash /opt/smart-edit/deploy/remote-setup.sh
#   SEED_USERS=1 bash /opt/smart-edit/deploy/remote-setup.sh   # 同时写入演示账号
#
# 幂等：可重复执行；系统依赖只在缺失时 apt 安装，venv 只在缺失时创建，服务每次都重启。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/smart-edit}"
PY="${APP_DIR}/.venv/bin/python"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
SEED_USERS="${SEED_USERS:-0}"

log() { printf '\n== %s\n' "$*"; }

[ -f "${APP_DIR}/.env" ] || { echo "missing ${APP_DIR}/.env — run deploy/deploy.sh from your machine"; exit 1; }

log "1/7 系统依赖（nginx / python3-venv / rsync）"
export DEBIAN_FRONTEND=noninteractive
missing=""
command -v nginx >/dev/null 2>&1 || missing="nginx"
command -v rsync >/dev/null 2>&1 || missing="${missing} rsync"
# `import venv` is satisfied by the stdlib alone; ensurepip is what python3-venv adds.
python3 -c 'import ensurepip' >/dev/null 2>&1 || missing="${missing} python3-venv"
if [ -n "${missing// /}" ]; then
  apt-get update -y
  # shellcheck disable=SC2086
  apt-get install -y ${missing} python3-pip ca-certificates curl
else
  echo "已安装，跳过"
fi

log "2/7 Python 依赖（${APP_DIR}/.venv）"
# A venv created without ensurepip is unusable; recreate instead of trusting the directory.
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  rm -rf "${APP_DIR}/.venv"
  python3 -m venv "${APP_DIR}/.venv"
fi
"$PY" -m pip install --upgrade pip wheel >/dev/null
"$PY" -m pip install -i "$PIP_INDEX" -e "${APP_DIR}"

log "3/7 运行时目录"
mkdir -p "${APP_DIR}/data" "${APP_DIR}/runs"
chmod 755 "${APP_DIR}/data" "${APP_DIR}/runs"

log "4/7 systemd 服务 smart-edit（127.0.0.1:8000）"
install -m 644 "${APP_DIR}/deploy/smart-edit.service" /etc/systemd/system/smart-edit.service
systemctl daemon-reload
systemctl enable smart-edit >/dev/null 2>&1 || true
systemctl restart smart-edit

ok=0
for _ in $(seq 1 60); do
  if curl -fsS -m 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  echo "后端没有起来，最近日志："
  journalctl -u smart-edit -n 120 --no-pager || true
  exit 1
fi
printf 'health: %s\n' "$(curl -s http://127.0.0.1:8000/health)"

log "5/7 nginx 站点（:8082 -> web/dist + /api -> :8000）"
install -m 644 "${APP_DIR}/deploy/nginx-smart-edit.conf" /etc/nginx/sites-available/smart-edit.conf
ln -sf /etc/nginx/sites-available/smart-edit.conf /etc/nginx/sites-enabled/smart-edit.conf
nginx -t
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx 2>/dev/null || systemctl restart nginx

log "6/7 本机防火墙（ufw / firewalld）"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 8082/tcp
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  # Ubuntu + docker on this ECS ships firewalld active with only 8080 open; without this the
  # public IP answers "Connection refused" even when the Aliyun security group allows 8082.
  firewall-cmd --permanent --add-port=8082/tcp >/dev/null
  firewall-cmd --reload >/dev/null
  echo "firewalld ports: $(firewall-cmd --list-ports)"
else
  echo "未检测到启用中的 ufw/firewalld（阿里云安全组仍需放行 8082/tcp）"
fi

if [ "$SEED_USERS" = "1" ]; then
  log "7/7 写入演示账号（scripts/seed_identity_users.py）"
  cd "$APP_DIR"
  "$PY" scripts/seed_identity_users.py
else
  log "7/7 跳过演示账号写入（需要时：SEED_USERS=1 bash deploy/remote-setup.sh）"
fi

log "完成"
systemctl --no-pager --lines=0 status smart-edit | head -5
ss -lntp | grep -E ':(8000|8082)\b' || true