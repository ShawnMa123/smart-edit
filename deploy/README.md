# 部署到阿里云 ECS（控制台在 **8082**）

```text
浏览器 ──HTTP :8082──> nginx ──┬─ /        -> /opt/smart-edit/web/dist（Vite 构建产物，SPA 回退）
                               ├─ /api/*   -> 127.0.0.1:8000（uvicorn，去掉 /api 前缀）
                               └─ /health  -> 127.0.0.1:8000/health
```

- 后端：`systemd` 服务 `smart-edit`，单 worker（run 状态是进程内的，多 worker 会把同一 run 拆到不同进程）。
- 前端：本机构建好 `web/dist` 再上传，服务器不需要 node。
- 数据：`/opt/smart-edit/data/{host,assistant}.db`（SQLite）+ `/opt/smart-edit/runs/`（上传件与 run 产物）；账号体系直连 RDS，不走 15432 隧道。

## 首次部署

```bash
cp deploy/env.ecs.example deploy/env.ecs   # 填 SMART_EDIT_DATABASE_URL / 模型 key（该文件已 gitignore）
./deploy/deploy.sh                          # 构建前端 → rsync → 远端 pip/systemd/nginx → 外网自检
./deploy/deploy.sh --seed-users             # 首次部署时把 README 里的演示账号写进 RDS
```

默认目标：`root@59.110.213.187`，私钥 `~/.ssh/team04_ecs`。可覆盖：

```bash
ECS_HOST=root@1.2.3.4 SSH_KEY=~/.ssh/other PUBLIC_URL=http://1.2.3.4:8082 ./deploy/deploy.sh
```

其它开关：

| 开关 | 作用 |
|---|---|
| `--no-build` | 复用已有 `web/dist`（只改了后端时用） |
| `--remote-only` | 不同步代码，只重装 systemd/nginx 配置 |
| `--seed-users` | 执行 `scripts/seed_identity_users.py`（会把这几个账号密码重置为 README 里的值） |

## 阿里云安全组必须放行 8082

安全组是网络层的白名单，服务器上 `ss -lntp` 能看到 nginx 监听也无济于事。控制台：
**ECS → 实例 → 安全组 → 配置规则 → 入方向 → 手动添加**

| 字段 | 值 |
|---|---|
| 端口范围 | `8082/8082` |
| 授权对象 | `0.0.0.0/0`（仅自己用可填办公/家庭出口 IP） |
| 协议类型 | 自定义 TCP |

## 主机防火墙：这台 ECS 上的 firewalld 也要放行 8082

第一次部署时外网一直 `Connection refused`（47ms 就 RST，不是超时），安全组放行后仍然如此。
根因是 **firewalld 在跑，`public` zone 只开了 `8080/tcp`**：

```bash
firewall-cmd --list-ports        # 之前只有 8080/tcp
firewall-cmd --permanent --add-port=8082/tcp
firewall-cmd --reload
```

`deploy/remote-setup.sh` 的第 6 步现在会自动检测 ufw / firewalld 并放行 8082，重复部署不会丢。

> 判断口径：`Connection refused`（秒级 RST）多半是主机防火墙；`timeout`（一直挂着）多半是安全组。

放行后本机验证：

```bash
curl http://59.110.213.187:8082/health   # {"status":"ok","auth_mode":"pg"}
```

## 日常运维（在 ECS 上）

```bash
systemctl status smart-edit          # 后端状态
journalctl -u smart-edit -f          # 后端日志（含每次请求的 request_id）
systemctl restart smart-edit         # 重启后端
tail -f /var/log/nginx/smart-edit.access.log /var/log/nginx/smart-edit.error.log
systemctl reload nginx               # 改完 /etc/nginx/sites-available/smart-edit.conf 后
```

更新代码：本地再跑一次 `./deploy/deploy.sh`（`rsync --delete` 会同步删除服务器上已移除的文件，但 `.venv/`、`runs/`、`data/`、`.env` 受保护，不会被删）。

只改了后端：

```bash
./deploy/deploy.sh --no-build
```

## 演示账号（RDS 中已存在）

| 邮箱 | 密码 | 角色 |
|---|---|---|
| admin@atlas-trade.test | AtlasAdmin!2026 | Organisation administrator |
| applicant@atlas-trade.test | Applicant!2026 | Applicant |
| bankops@atlas-trade.test | BankOps!2026 | Bank Operations（一审） |
| compliance@atlas-trade.test | Compliance!2026 | Compliance（二审） |
| auditor@atlas-trade.test | Auditor!2026 | Auditor |

## 本次部署顺手修掉的一个前端 bug

部署后第一次登录会发现演示文档被清空（`0 characters`、`server draft rev 2`）。原因不在后端：

`web/src/rich/useRichEditor.ts` 里的 `editor.setEditable(editable)` 默认 `emitUpdate = true`，
挂载时会发出一次「更新」，`App` 把它当成用户输入（此时编辑器内容还是空的），于是
`if (!userEditedRef.current)` 分支不再应用刚拉到的服务端草稿，并把空内容存回去覆盖 rev 1。

修复：`editor.setEditable(editable, false)`，并补了回归用例
`web/src/rich/useRichEditor.test.tsx`（去掉 `false` 时两条用例会红）。本地 `npm --prefix web run test`
542 passed / 12 skipped。

## 法规风险扫描（legal 模块）

`Legal → Document check` 扫描当前草稿：条款计划 → 确定性检查（要素/日期/高风险措辞）→ 逐条款
`/v1/retrieve` 取法条 → 豆包在给定证据内归纳 → 可选联网补检 → 报告带草稿锚点、覆盖率与闸门。
规格见 `openspec/changes/legal-document-risk-scan/`。

| 变量 | 默认 | 作用 |
|---|---|---|
| `SMART_EDIT_LEGAL_MAX_CLAUSES` | `12` | 单次扫描的条款上限（超出会标 `truncated`） |
| `SMART_EDIT_LEGAL_CLAUSE_CHARS` | `1200` | 单条款字符上限 |
| `SMART_EDIT_LEGAL_SCAN_DEADLINE` | `90` | 扫描总预算（秒）；超时余下条款记 `deadline_exceeded` |
| `SMART_EDIT_LEGAL_COVERAGE_RATIO` | `0.6` | 低于该覆盖率，闸门带 `limited_coverage` |
| `SMART_EDIT_LEGAL_WEB_DEFAULT` | `0` | 联网补检的部署默认；UI 勾选优先 |
| `SMART_EDIT_LEGAL_MAX_WEB_CALLS` | `2` | 单次扫描联网调用上限（当前实现最多 1 次） |
| `SMART_EDIT_LEGAL_COMPOSE_TIMEOUT` | `45` | 单条款综合的超时 |
| `SMART_EDIT_LEGAL_MAX_EVIDENCE` | `5` | 每条条款最多交给模型的证据条数 |
| `SMART_EDIT_LEGAL_DB` | `runs/legal.db` | run/report 的 SQLite 路径 |

排障口径：

- **每个条款都是 `composer_unavailable`**：`SMART_EDIT_ASSISTANT_MODEL/API_KEY` 没配，或
  `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED` 不为 1。确定性检查仍然会给出结论。
- **大量 `uncovered:XX`**：语料没有覆盖该法域/主题；这是如实告知，报告会把它列进闸门原因。
- **`stale_snapshot`**：扫描期间草稿被保存过；重新扫描即可。
- **联网从不发生**：未在面板勾选 `Use web search…`，或 `SMART_EDIT_LEGAL_WEB_DEFAULT=0`（默认）。

## 已知取舍 / 排障

- **无 TLS**：目前是 `http://IP:8082`，所以 `SMART_EDIT_AUTH_COOKIE_SECURE=0`（带 `Secure` 的 cookie 在 HTTP 下不会被浏览器回传，表现为“登录成功但立刻 401”）。挂上 HTTPS 后删掉这行即可。
- **进程内 run 状态**：`systemctl restart smart-edit` 之后旧 `thread_id` 会返回 `unknown_run`，需要重新创建 run；文档/审批数据在 SQLite + RDS 里，不受影响。
- **8082 外网不通**：先确认安全组（见上），再 `ss -lntp | grep 8082`、`systemctl status nginx`。
- **登录 401 / 无法登录**：`journalctl -u smart-edit | tail -30`；`SMART_EDIT_AUTH_MODE=pg` 启动时若连不上 RDS 会直接失败（fail closed），不会静默降级到 fake。
- **`.env` 权限**：上传时会设置成 `600`，里面是数据库密码与模型 key，不要提交到 git。
- **服务以 root 运行**：为了少踩 SQLite/端口权限坑；若要做长期环境，建议新建 `smart-edit` 用户并把 `/opt/smart-edit` 的 `data/`、`runs/` 交给他。
- 前端单包 ~1MB（gzip 后 ~310KB），3Mbps 带宽下首屏约 1~3s；nginx 已开 gzip 与静态缓存。