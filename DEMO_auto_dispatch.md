# 自动投递页面测试指南（终审通过 → 下游）

> 适用：`automation-bank-ops-auto-dispatch`（31/31 tasks 已完成）
> 目标：在**页面上**完整走通「配置一次 → 终审 → 自动投递 → 运行面板可追溯」，并验证 shadow、人工放行、
> kill switch 与失败兜底。
>
> 关键前提：本功能依赖**真实的 PG 身份与两级审批**（`AUTH_MODE=pg`）。页面上的 `Demo data` / fake 身份
> 不会产生真实 submission，因此**无法触发自动投递**；请用 ECS 演示环境，或本机连 PG。

## 30 秒速览（最短路径）

```text
bankops   → Automation → Automate：Save current draft as template → Find variables → Confirm
          → Document type 选该模板 → Bind（必须）
          → Add connector：http://127.0.0.1:18080 + /hooks/smart-edit + No auth
bankops   → Rules：New rule（模板 + 连接器，mode 保持 Shadow）→ Save rule
applicant → Start editing → 粘贴样例 → Submit new version → Submit for approval
bankops   → Approval → First approval → Approve
compliance→ Approval → Second approval → Approve
（跑 worker：systemctl start smart-edit-automation，或 python -m app.automation.worker --once）
bankops   → Automation → Runs：第一轮应看到 Shadowed
bankops   → Rules：档位改 Auto send；重置文档 + 重新 Bind 后重走审批 → Runs 显示 Sent
后续文档  → applicant 文档头 New document → 粘贴 → bankops Bind → 提交（无需重置上一份）
```

---

## 0. 你会验证到的 5 件事

| # | 场景 | 页面上的预期 |
|---|---|---|
| 1 | 新规则默认 shadow | 终审后 Runs 出现 `Shadowed`，下游**没有**收到请求，回执表没有新行 |
| 2 | 升档 `auto_send` 后终审 | Runs 显示 `Sent`，交付徽标 `Delivery: Sent`，回执带 `system:automation` |
| 3 | `needs_review` 人工兜底 | 终审后停在 `Needs review`，点 **Release** 后 worker 才发送 |
| 4 | 全局 kill switch | 面板顶部变红提示，原本 `auto_send` 的规则只产生 `shadowed` |
| 5 | 失败/跳过可读 | 白名单拒绝 → `Needs attention`（不重试）；未绑定/无规则 → `not_configured` + 原因 |

---

## 1. 环境与账号

### 1.1 账号（`scripts/seed_identity_users.py` 预置）

| 账号 | 密码 | 角色 | 在本流程里做什么 |
|---|---|---|---|
| `applicant@atlas-trade.test` | `Applicant!2026` | Applicant | 编辑样例文档、提交审批 |
| `bankops@atlas-trade.test` | `BankOps!2026` | Bank Ops | 建模板/连接器/规则、绑定文档、**一审**、看 Runs |
| `compliance@atlas-trade.test` | `Compliance!2026` | Compliance | **二审**；Automation 只读 |
| `admin@atlas-trade.test` | `AtlasAdmin!2026` | Org admin | 全权限（可选） |

> `applicant` 看不到 Automation 入口（权限矩阵如此）；`compliance` 能看到但只能读（没有 configure/dispatch）。
> 这不是 bug，是本次权限收口的验收点。

### 1.2 方案 A：用 ECS 演示环境（推荐，已有模板/连接器/echo）

```bash
# 1) 确认 echo 下游活着（自动发送的目标）
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'curl -s http://127.0.0.1:18080/health'
# 期望：{"status": "ok"}；没有就起：
#   cd /opt/smart-edit && nohup .venv/bin/python scripts/echo_downstream.py --port 18080 >/tmp/echo.log 2>&1 &

# 2) 确认/启动 worker（部署脚本默认不启用它）
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'systemctl status smart-edit-automation --no-pager | head -5'
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'systemctl enable --now smart-edit-automation && systemctl restart smart-edit-automation'
# 等价的一次性执行（不想常驻时）：
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && set -a && . ./.env && set +a && .venv/bin/python -m app.automation.worker --once'

# 3) 确认 kill switch 是开的（1 = 允许 auto_send）
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'grep -n "SMART_EDIT_AUTOMATION" /opt/smart-edit/.env || true'
```

浏览器打开 **http://59.110.213.187:8082/**（Chrome，宽度 ≥ 1400px，右侧面板才完整展开）。

### 1.3 方案 B：本机跑（需要 PostgreSQL）

```bash
# 终端 1：API（PG 身份）
export SMART_EDIT_AUTH_MODE=pg
export SMART_EDIT_DATABASE_URL='postgresql://...'    # 与 .env 一致
export SMART_EDIT_HOST_DB=runs/host.db
export SMART_EDIT_AUTOMATION_ALLOWED_HOSTS=127.0.0.1
export SMART_EDIT_AUTOMATION_ALLOW_HTTP=1
.venv/bin/uvicorn app.api.main:app --port 8000 --reload

# 终端 2：前端
cd web && npm run dev            # http://127.0.0.1:5173

# 终端 3：echo 下游
.venv/bin/python scripts/echo_downstream.py --port 18080

# 终端 4：worker（一次性；想常驻就去掉 --once）
SMART_EDIT_HOST_DB=runs/host.db .venv/bin/python -m app.automation.worker --once
```

> 本机首次使用需先建账号与演示文档：
> `SMART_EDIT_AUTH_MODE=pg .venv/bin/python scripts/seed_identity_users.py --reset`

### 1.4 页面前置检查（30 秒）

1. 用 **bankops** 登录 → 右侧面板应出现 **Automation** 标签（chip 显示 `Server`）。
2. 点开 Automation → 内部应有四个页签：**Automate / Rules / Runs / Sandbox**。
3. 当前文档是 `Demand Guarantee Application`（`demo-document`），顶部应为 `Draft`。

---

## 2. 配置（用 bankops）

> 顺序很重要：**模板 → 变量 → 绑定文档 → 连接器 → 规则**。绑定是自动投递的唯一判据。

### 2.1 先让申请人把样例文档放进草稿（30 秒）

用 **applicant** 登录：

> 如果文档已经不是 `Draft`（例如之前演示已走到 `Approved`，终态只读），先按 **§4.1** 重置文档再回来。

1. 编辑器底部点 **Start editing**（拿到编辑锁）。
2. `Cmd/Ctrl+A` 全选，粘贴 **附录 A** 的样例文本。
3. 等 2 秒自动保存，或随时点编辑器底部 **Save**（快捷键 `Cmd/Ctrl+S`）立即保存；
   状态行显示 **Saved to server** 后再提交。
4. 点 **Release lock**（把锁交出去，避免干扰后续配置）。

### 2.1b 多文档：新建 / 打开（提交后继续工作）

文档头新增 **New document**（applicant / org admin / dept admin 有 `document.create`）：

1. 点 **New document** → 服务端创建一份新草稿（`Untitled document`）并自动切换过去；
   原来的文档保留，不会被清空。
2. 新文档是**未绑定模板**的，若要自动投递，bankops 仍需在 Automation → Automate →
   `Document type` 选模板 → **Bind**。
3. 顶部 **Approval → Documents** 页签会列出所有可打开的文档（标题 + 状态 + revision）：
   - **Open**：真正把那份文档加载进编辑器（已提交/已批准的是只读）；
   - **New document**：同样可以在这里新建。

> 因此「一份文档提交后不能编辑」不再阻塞你：直接 **New document** 继续下一份；
> 想看上一份就 Approval → Documents → Open（只读），或在该行的提交上点 View submitted version 看快照。

> **我的提交（My submissions）现在是跨文档的工作区列表**：显示每份提交所属的文档标题、状态与 revision，
> 刷新页面或切换当前文档后仍然能看到之前提交的所有文档（每行都有 **Open document**）。

### 2.2 保存模板并确认变量（bankops）

1. Automation → **Automate** → `1 · Template (server)`。
2. **Template name** 填 `Auto dispatch demo`（默认是首行标题，建议改短）。
3. 点 **Save current draft as template** → 提示保存成功，列表出现
   `Auto dispatch demo v1.0.0 · 0 vars`。
4. 点 `2 · Fields` 里的 **Find variables with AI**（没有模型时自动退化为确定性抽取，不会 500）。
5. 复核建议列表（`Applicant / Beneficiary / Amount / Currency / Expiry date …`），点
   **Confirm N variables**。
6. 期望：顶部显示 `N confirmed: Applicant, Beneficiary, Amount, Currency, Expiry date`。

### 2.3 绑定文档（关键，漏了会得到 `no_binding`）

1. 仍在 Automate → `1 · Template (server)` 底部：
   `Document type: not bound` → 下拉选 `Auto dispatch demo v1.0.0`。
2. 点 **Bind**。
3. 期望：`Document type: Auto dispatch demo`，右侧标签从 `not bound` 变成 **`bound`**。
4. 审计：服务端 `host_audit` 表新增 `document_template_bound`（含操作者、文档、模板）。
   注意：页面右侧的 **Activity** 是 PG 事件流，不展示 `host_audit`；要看这条用下面的 SQL：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
 'cd /opt/smart-edit && .venv/bin/python -c "import sqlite3;c=sqlite3.connect(\"data/host.db\");print(c.execute(\"select event_type,actor,created_at from host_audit order by created_at desc limit 5\").fetchall())"'
```

### 2.4 连接器（真实发送目标）

Automate → `3 · Downstream` → 展开 **Add connector**：

| 字段 | 值 |
|---|---|
| Connector name | `Local echo (auto)` |
| Connector base URL | `http://127.0.0.1:18080`（ECS 上就是服务器本机） |
| Connector path | `/hooks/smart-edit` |
| Connector auth | `No auth` |
| OpenAPI spec / custom fields | 留空（走 legacy flat body，echo 同样接收） |

点 **Save connector**。保存后该连接器会被自动选中
（`Target: Local echo (auto) · http://127.0.0.1:18080`）。

> 现场如果已有 `Local echo (demo)`，直接在下拉里选它即可。

### 2.5 规则（默认 shadow）

1. 切到 **Rules** 页签 → `New rule`：
   - Rule name：`Guarantee → ERP`
   - Rule template：`Auto dispatch demo`
   - Rule connector：`Local echo (auto)`
   - Rule mode：**`Shadow (record only)`**（默认值，别改）
2. 点 **Save rule** → 提示 `Rule saved. New rules stay in shadow until you raise the tier.`
3. 规则行应显示：`Shadow (record only)`、`required`、无 warning。

### 2.6 dry-run（不发请求地看请求体）

1. 保持当前文档打开，点规则行的 **Dry-run on this document**。
2. 期望出现 `rule-dry-run` 区块：`POST http://127.0.0.1:18080/hooks/smart-edit`、`would_send` 里有
   `values`（`amount: USD 250,000.00` 等）、`issues` 为空、`refusal` 为空。
3. 此时下游**不应**收到请求（echo 终端没有新日志）。

---

## 3. 第一轮：shadow —— 终审只记录、不外发

### 3.1 applicant 提交

1. 用 **applicant** 登录，打开同一份 `Demand Guarantee Application`。
2. 底部 **Start editing** → **Submit new version**。
3. 对话框 `Submit for approval`：确认目标链 `Bank Operations → Compliance`，点 **Submit for approval**。
4. 期望：文档顶部 `Pending first approval`，编辑器变只读，锁释放。

### 3.2 bankops 一审

1. **Sign out** → 用 **bankops** 登录。
2. 顶部 **Approval** → 标签 **First approval**。
3. 面板最上方新增 **`Current document` 卡片**：文档标题 + 状态徽标 + `revision N`，并提供两个入口：
   - **Open document**：关闭审批弹窗、切回左侧 **Document** 编辑器（看当前草稿）；
   - **View submitted version**：直接加载这条提交的冻结快照（等价于点下面对应记录）。
   - 如果还没提交，这里显示 `No submission yet — this is the working draft.`。
4. 左侧 **Pending requests** → 点待办记录（`Demand Guarantee Application`）。
5. 右侧详情核对 **Submitted snapshot text**（就是你粘贴的样例），点 **Approve**。
6. 期望：状态 `Pending second approval`，时间线出现 `First approver — approve`。

> 每条待办右侧（`My submissions` 是卡片下方）也有 **Open document**；详情里也有 **Open document**，
> 方便从“看快照”随时回到编辑器。点击左侧竖排 **Document / Versions** 现在会**同时关闭**当前模块弹窗
> 并切换面板（此前只切换后面的面板，弹窗仍在最上层，看起来像“没反应”）。

### 3.3 compliance 二审（终审）

1. **Sign out** → 用 **compliance** 登录。
2. **Approval** → **Second approval** → 选中记录 → **Approve**。
3. 期望：状态 **`Approved`**，文档只读。

### 3.4 运行 worker

ECS（常驻 unit 会 5 秒内自动处理；想手动触发）：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && set -a && . ./.env && set +a && .venv/bin/python -m app.automation.worker --once'
```

本机：`SMART_EDIT_HOST_DB=runs/host.db .venv/bin/python -m app.automation.worker --once`

期望输出：`{"events": 1, "jobs": 1}`（只命中一条规则时；多规则 fan-out 时 `jobs` 等于命中的下游数）。

### 3.5 在 Runs 里确认 shadow

1. 切回 **bankops** → Automation → **Runs**（面板每次打开都会重新拉取；也可切走再切回）。
2. 期望：
   - 顶部横幅：`Automatic sending is enabled globally …`
   - 交付徽标：**`Delivery: Shadowed`**
   - 列表一行：`Shadowed · Local echo (auto) · Guarantee → ERP · shadow · required`
   - **不应出现** Release/Retry/Cancel 按钮
3. Automation → Automate → `Recent dispatches` **没有新回执**（shadow 不写回执）。

---

## 4. 第二轮：升档 auto_send —— 终审后真实发送

> 因为 `approved` 后文档永久只读，复测必须重置演示文档。重置会**删掉绑定**（文档行重建），
> 但模板/连接器/规则都保留。

### 4.1 准备第二份文档（两种方式）

> `Approved` 后文档只读。**推荐直接用 applicant 的 `New document`**（保留上一份提交，无需 reset）：
>
> 1. applicant → 文档头 **New document** → 新草稿（`Untitled document`）自动打开；
> 2. 粘贴样例 → 等 **Saved to server**。

如果想继续用 `demo-document` 本身（会清掉它的历史提交），再执行：

```bash
# ECS
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py'
# 本机
SMART_EDIT_AUTH_MODE=pg .venv/bin/python scripts/seed_identity_users.py
```

脚本会：重建 `demo-document`、恢复密码、并清理该文档的历史
`submissions / approval_requests / automation_jobs / automation_dispatches`（Runs 不残留上一轮）。

浏览器 **F5**（登录会话仍有效）。

### 4.2 绑定这份文档（自动投递必需，每份文档都要绑）

用 **bankops**：Automation → Automate → `Document type` 下拉选 `Auto dispatch demo` → **Bind** →
标签变 **bound**。

> 不绑定也能审批，但自动投递会得到 `Not configured (no_binding)`。

### 4.3 升档并留痕

1. **Rules** → 规则行 `Tier for Guarantee → ERP` 下拉：`Shadow` → **`Auto send`**。
2. 提示 `Rule "Guarantee → ERP" is now auto_send.`
3. 审计：`host_audit` 新增 `automation_rule_mode_changed`，payload 含 `from: shadow`、`to: auto_send`
   （页面 Activity 不展示 host_audit，用 `select event_type,actor,payload_json from host_audit` 查）。

### 4.4 再走一遍「编辑 → 提交 → 一审 → 二审」

按 §2.1 / §3.1–3.3 重复（applicant 粘贴样例、提交；bankops Approve；compliance Approve）。

### 4.5 跑 worker 并交叉验证

```bash
# 同 §3.4
```

1. **Runs**：交付徽标 **`Delivery: Sent`**；列表 `Sent`；`Details` 时间线
   `queued → sending → sent`；`receipt_id` 有值。
2. **Automate → Recent dispatches**：新增一条 `succeeded · 200 · …ms` 并带响应摘录
   （echo 返回 `{"accepted": true, "path": "/hooks/smart-edit", …}`）。
3. **echo 终端**：出现 `POST /hooks/smart-edit values=[…]`。
4. 用 API 核对回执关联字段（可选）：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
 'cd /opt/smart-edit && .venv/bin/python -c "import sqlite3,json;c=sqlite3.connect(\"data/host.db\");c.row_factory=sqlite3.Row;print(json.dumps([dict(r) for r in c.execute(\"select job_id,rule_id,submission_id,trigger,status,created_by from automation_dispatches order by created_at desc limit 3\")],ensure_ascii=False,indent=2))"'
```

期望：`job_id/rule_id/submission_id` 都不为空、`trigger=final_approval`、`created_by=system:automation`。

5. （可选）**Activity**：worker 以 PG 身份运行时（ECS 默认），右侧 **Activity** 会出现
   `delivery.sent`（actor `Automation`），detail 含 `document_id / job_id / rule_id / connector_id / status`。

---

## 5. 第三轮：needs_review —— 人工放行

1. **Rules** → 档位改为 **`Needs review`**。
2. 重置文档（§4.1）→ 重新绑定（§4.2）→ applicant 提交 → 一审 → 二审 → 跑 worker。
3. **Runs** 期望：
   - 列表：`Needs review · Local echo (auto) · …`
   - 交付徽标：`Delivery: Needs review`
   - 该行出现 **Release** 与 **Cancel**，**没有** Retry
   - 下游仍未收到请求（echo 无新日志）
4. 点 **Release** → 提示 `Job released to the worker.` → 该行变 `Queued`。
5. 再跑一次 worker → `Sent`，echo 收到一次请求。

> 放行使用同一幂等键的下一 attempt；同一 submission 不会重复发送已成功的下游。

---

## 6. 开关与失败场景（各 1–2 分钟）

### 6.1 全局 kill switch（关闭自动发送）

```bash
# ECS：改成 0（没有这一行就追加），重启 API（横幅数据来自 API 进程）与 worker（发送决策来自 worker 进程）
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  "cd /opt/smart-edit && (grep -q '^SMART_EDIT_AUTOMATION_AUTO_SEND=' .env \
     && sed -i 's/^SMART_EDIT_AUTOMATION_AUTO_SEND=.*/SMART_EDIT_AUTOMATION_AUTO_SEND=0/' .env \
     || echo 'SMART_EDIT_AUTOMATION_AUTO_SEND=0' >> .env) \
   && systemctl restart smart-edit smart-edit-automation"
```

1. 规则保持 `Auto send`，重走一轮终审 + worker。
2. 期望：Runs 顶部横幅变红
   `Automatic sending is disabled globally: every auto_send rule behaves like shadow …`；
   job 为 `Shadowed`；交付徽标 `Shadowed`；**没有** 回执、echo 没请求。
3. 想恢复：把同一命令里的 `=0` 换成 `=1` 再执行一次。

### 6.2 worker 停掉（审批照常，但不投递）

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'systemctl stop smart-edit-automation'
```

重走一轮终审（不跑 `--once`）→ Runs 里**没有新 job**；`Recent dispatches` 也没有新回执。
启动 worker 后 5 秒内补跑，Runs 才出现记录。这就是回滚第一步的语义。

### 6.3 规则暂停 → `not_configured (no_rule)`

1. **Rules** → 规则行 **Pause**（`enabled=false`）。
2. 重走一轮终审 + worker。
3. 期望：Runs 交付徽标 `Delivery: Not configured`，下面一行
   `No enabled rule matches this template, so nothing was queued.`；列表出现 `Skipped` 行。
4. 恢复：**Resume**。

### 6.4 未绑定文档 → `not_configured (no_binding)`

1. 重置文档（§4.1），**跳过** 4.2 的 Bind。
2. 直接走一轮终审 + worker。
3. 期望：`Delivery: Not configured` +
   `This document has no template binding, so automatic delivery is skipped.`
4. 绑定后再走一轮即恢复。

### 6.5 下游拒绝（白名单）→ `Needs attention`，不重试

1. 建一个连接器 `Refusal demo`：base URL `https://example.com`、path `/hook`、No auth
   （不在 `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS` 中）。
2. 把规则的 connector 改成 `Refusal demo`（或新建一条规则指向它，两条规则会 fan-out 到两个下游）。
3. 重走终审 + worker。
4. 期望：
   - 该 job `Needs attention`，`error_code` 类似 `host_not_allowed`；
   - 行内出现 **Retry** 与 **Cancel**；
   - 交付徽标 `Needs attention`；
   - `Recent dispatches` 里一条 `refused`（没有真实外发）。
5. 点 **Retry** → `Queued`（但仍会因白名单失败；用于验证重试入口）。

> 5xx 退避重试（1m/5m/30m，3 次）与 `partial` 中间态需要可控的下游状态，页面不易构造，
> 已由 `tests/test_automation_jobs.py` / `tests/test_automation_worker.py` 覆盖。

---

## 7. 复测与清理

- 每轮复测：**重置文档（§4.1） → 重新 Bind（§4.2） → 提交 → 一审 → 二审 → worker**。
- 只重置文档：`scripts/seed_identity_users.py`（不带 `--reset`）。
- 连账号一起重建：加 `--reset`（会 TRUNCATE 身份表并重新 seed，所有会话失效）。
- 清掉演示规则/模板（可选）：

```bash
# 页面：Rules → Disable；Automate → 模板 Delete
# 或直接看数据：
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && .venv/bin/python -c "import sqlite3;c=sqlite3.connect(\"data/host.db\");print(c.execute(\"select rule_id,name,mode,enabled from automation_rules\").fetchall())"'
```

---

## 8. 预期结果速查表

| 你的操作 | Runs 交付徽标 | Runs 列表 | 回执 / echo |
|---|---|---|---|
| 新规则 shadow + 终审 | `Shadowed` | `Shadowed` | 无 / 无 |
| 升 `auto_send` + 终审 | `Sent` | `Sent` | `succeeded` / 一次请求 |
| `needs_review` + 终审 | `Needs review` | `Needs review` + Release/Cancel | 无 / 无 |
| 放行后 + worker | `Sent` | `Sent` | `succeeded` / 一次请求 |
| kill switch 关闭 | `Shadowed` | `Shadowed` | 无 / 无 |
| 规则暂停 | `Not configured` | `Skipped (no_rule)` | 无 / 无 |
| 未绑定 | `Not configured` | `Skipped (no_binding)` | 无 / 无 |
| 白名单拒绝 | `Needs attention` | `Needs attention` + Retry/Cancel | `refused` / 无 |

---

## 9. 排错

| 现象 | 原因 / 处理 |
|---|---|
| 右侧没有 Automation 标签 | 用的是 applicant/member；换 bankops 或 admin |
| Automation 里只有 3 个页签（无 Runs） | 前端未更新到本版本；重新构建/部署 `web/dist` |
| 终审后 Runs 一直空 | worker 没跑：`systemctl status smart-edit-automation`，或手动 `--once` |
| worker 输出 `events: 0` | 终审事件已被之前的 worker 批次消费；看 `automation_jobs` 是否已有记录 |
| Runs 显示 `Not configured (no_binding)` | 忘了 §2.3/§4.2 的 Bind；绑定不会随文档重置保留 |
| `Not configured (no_rule)` | 规则被暂停/删了，或规则的 template 名与绑定名不一致 |
| `Needs attention / host_not_allowed` | 连接器主机不在 `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS`；或忘了 `..._ALLOW_HTTP=1` |
| `Needs attention / transport_error` | echo 没起：`curl http://127.0.0.1:18080/health` |
| 交付徽标为 `Partial` | 还有 required 下游在排队；等 worker 跑完再看 |
| 文档无法再次编辑 | `Approved` 是终态；用文档头 **New document** 建一份新草稿继续（或按 §4.1 重置） |
| 提交后想换一份继续做 | 文档头 **New document**；新文档记得让 bankops 重新 **Bind** 模板才会自动投递 |
| bankops 无法编辑文档 | `bank_ops` 已有 `document.create` / `document.edit`：可新建/编辑草稿与 `returned`；`pending_*` / `approved` 仍冻结（任何角色都不能保存），需先 **Return** |
| bankops 编辑后如何提交 | `bank_ops` 仍没有 `approval.submit`：编辑完成后由 applicant 提交；也可以先 Return → applicant 修改并重新提交 |
| 点 Run spec audit 没反应 | 旧版本在纯 http 下没有 `crypto.subtle`，快照摘要抛错且请求未发出；本版已内置本地 SHA-256 回退，并会把快照失败显示成错误。硬刷新后再试 |
| 审计的不是我刚导入的 Andy 发票 | 导入文件只在 Import report 里预览；点 **Use this text** → 编辑器底部 **Save**（`Cmd/Ctrl+S`）落库后，再切到目标文档运行审计 |
| 提交的快照不是刚粘贴的内容 | 粘贴后先等 **Saved to server**，或点底部 **Save**（`Cmd/Ctrl+S`）再提交 |
| 点 Save 提示 “Nothing to save” | 当前没有未保存修改；状态行已是 `Saved to server` |
| 点 Save 提示 “needs a server draft and the edit lock” | 先 **Start editing** 拿到锁（审批中/已批准时不能保存） |
| 点左侧 **Document** 没反应 | 旧前端只切了弹窗后面的面板；本版本会同时关闭模块弹窗并切回编辑器，重新部署 `web/dist` 后再试 |
| Approval 里看不到“提交的版本” | 看面板最上方 `Current document` 卡片；没有 **View submitted version** 说明这条文档还没有 submission（页脚应是 `Draft`） |
| Approval → Documents 里点 Open 没内容 | Open 会真正加载那份文档；若为空，确认该文档正文已保存（`Saved to server`） |

---

## 附录 A · 样例文档（直接粘贴）

仓库文件：`fixtures/automation-samples/demand-guarantee-auto.txt`

```text
DEMAND GUARANTEE APPLICATION
Application type: guarantee
Applicant: Atlas Trading Ltd
Beneficiary: Meridian Exports Pte Ltd
Amount: USD 250,000.00
Currency: USD
Expiry date: 2027-06-30
Governing rules: URDG 758
Requested by: Applicant
```

为什么用它：

- 除首行标题外每行都是 `Label: value`，模板的确定性抽取一定能找到变量（不依赖模型）。
- `Amount` 带币种和千分位，能验证变量绑定（`USD 250,000.00` 原样进入请求体；如果连接器用
  OpenAPI/自定义字段声明为 `number`，会转换成数字）。
- 标签互不重复（`Amount` vs `Currency`），不会出现“同一行两个变量”。

备选样例（第二个下游/第二类文档，可另建模板 + 规则）：
`fixtures/automation-samples/commercial-invoice.txt`（含 `Buyer country: Iran`、`Invoice amount: USD 486,500.00`，
适合演示同一连接器服务不同模板）。

---

## 附录 B · 参数速查（按本指南配置）

| 对象 | 名称 / 值 |
|---|---|
| 文档 | `demo-document`（`Demand Guarantee Application`） |
| 模板 | `Auto dispatch demo` v1.0.0（变量：Applicant / Beneficiary / Amount / Currency / Expiry date …） |
| 绑定 | `documents.template_id/template_name` → 上述模板（Automate → Document type → Bind） |
| 连接器 | `Local echo (auto)` · `http://127.0.0.1:18080` · `/hooks/smart-edit` · No auth |
| 规则 | `Guarantee → ERP` · template `Auto dispatch demo` · connector `Local echo (auto)` · trigger `final_approval` · required |
| 档位 | `shadow` →（验收）`needs_review` → `auto_send` |
| 幂等键 | `auto:{rule_id}:{submission_id}`（手工重试用 `#attempt` 后缀） |
| 回执身份 | `created_by = system:automation`，`trigger = final_approval` |

---

## 附录 C · 不走 UI 的 API 验证（可选）

先用任意账号在浏览器登录，从 DevTools 复制 Cookie（或 `curl -c/-b` 登录）：

```bash
B=http://59.110.213.187:8082/api
curl -s -c /tmp/cj -X POST $B/auth/login \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  -d '{"email":"bankops@atlas-trade.test","password":"BankOps!2026"}'

# 开关状态
curl -s -b /tmp/cj $B/automation/settings

# 运行列表（按文档过滤）与单条详情
curl -s -b /tmp/cj "$B/automation/jobs?document_id=demo-document"
curl -s -b /tmp/cj "$B/automation/jobs/<job_id>"

# 文档交付聚合（含每个下游一行与 skipped 原因）
curl -s -b /tmp/cj "$B/automation/documents/demo-document/delivery"

# 人工操作
curl -s -b /tmp/cj -X POST $B/automation/jobs/<job_id>/release
curl -s -b /tmp/cj -X POST $B/automation/jobs/<job_id>/retry
curl -s -b /tmp/cj -X POST $B/automation/jobs/<job_id>/cancel
```

> 页面上 `/api` 前缀由 nginx 去掉；本机直连 uvicorn 时用 `http://127.0.0.1:8000` 且无 `/api`。

---

## 附录 D · 自动化回归（不用手点）

```bash
# 真实 echo 下游的端到端：shadow → 升档 → 两下游 sent；以及回滚演练
.venv/bin/python -m pytest tests/test_automation_auto_dispatch_e2e.py -q

# Runs API / 交付聚合 / 人工兜底状态机
.venv/bin/python -m pytest tests/test_automation_jobs.py -q

# worker：快照组包、幂等、5xx 重试、4xx 不重试、skip 原因
.venv/bin/python -m pytest tests/test_automation_worker.py tests/test_automation_rules.py -q

# 前端 Runs 面板
cd web && npx vitest run src/components/AutomationRunsPanel.test.tsx
```