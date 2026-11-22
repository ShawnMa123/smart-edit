下面是**只在网页上点**的逐步 guide（命令行只用于“启动 worker / 重置演示文档”这两个页面外的前置），每一步都写了你应看到的界面反馈。完整版（含排错与负向场景）也在仓库 `DEMO_auto_dispatch.md`。

---

## 0.0 一键种子数据（可选，但“导览有内容”需要它）

Rules / Runs 是**服务端状态**：新环境里两个面板都是空的，导览只能讲解。要在页面上看到真实规则和运行：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && set -a && . ./.env && set +a && .venv/bin/python scripts/seed_automation_demo.py'
```

会创建/复用：

- 文档 `Automation demo · trade application`（**真实提交 + Bank Ops/Compliance 双审 → Approved**）；
- 该文档的模板绑定 `Trade application (spec demo)`；
- 一条 **shadow** 规则 `Demo · Trade application (spec demo) → Trade intake (spec demo)`；
- 一条 **shadowed** 运行（worker 只生成请求、**不外发**）。

脚本是幂等的（同一 `rule + submission` 不会重复建 job），并且在发现同模板存在非 shadow 规则时会**拒绝执行**，
保证不会真的发送。之后：打开该文档可看到它自己的 Delivery；打开其它文档时 Runs 会显示“工作区最新运行”。

---

## 0. 先确认 3 个前置（不在页面上）

1. 打开 **http://59.110.213.187:8082/**（Chrome，窗口宽度 ≥ 1400px）。
2. 服务器上 **worker 必须启动**（部署脚本默认不启用它）：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'systemctl enable --now smart-edit-automation'
# 或者只跑一次：cd /opt/smart-edit && set -a && . ./.env && set +a && .venv/bin/python -m app.automation.worker --once
```

3. echo 下游活着：`curl -s http://127.0.0.1:18080/health` → `{"status": "ok"}`。

账号：

| 角色 | 账号 / 密码 | 用途 |
|---|---|---|
| Applicant | `applicant@atlas-trade.test` / `Applicant!2026` | 编辑、提交 |
| Bank Ops | `bankops@atlas-trade.test` / `BankOps!2026` | 配置、一审、看 Runs |
| Compliance | `compliance@atlas-trade.test` / `Compliance!2026` | 二审（终审） |

---

## 1. applicant：把样例文档放进草稿

1. 登录页填 **Email / Password** → 点 **Sign in**。
2. 中间编辑器底部点 **Start editing**（出现 `lock: this session`）。
3. `Cmd/Ctrl+A` → 粘贴下面文本：

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

4. 等 2 秒，底部变 **Saved to server**。
5. 点 **Release lock**。

---

## 2. bankops：一次配置（模板 → 变量 → 绑定 → 连接器 → 规则）

1. 右上角 **Sign out** → 用 bankops 登录。
2. 右侧面板点 **Automation**（显示为 `Automation · server`，chip 是 `Server`）。
3. 确认内层四个页签：**Automate / Rules / Runs / Sandbox**。

### 2.1 保存模板
4. 在 **Automate → `1 · Template (server)`**：**Template name** 填 `Auto dispatch demo`。
5. 点 **Save current draft as template** → 列表出现 `Auto dispatch demo v1.0.0 · 0 vars`。
   （若面板显示 `Section 1/4` + Back/Next，用 **Next** 走到对应小节。）

### 2.2 确认变量
6. 到 **`2 · Fields`** → 点 **Find variables with AI**。
7. 看到建议列表（Applicant / Beneficiary / Amount / Currency / Expiry date …）→ 点
   **Confirm N variables** → 顶部出现 `N confirmed: …`。

### 2.3 绑定文档（**最容易漏，漏了就是 no_binding**）
8. 回到 **`1 · Template (server)`** 底部：`Document type: not bound` → 下拉选 `Auto dispatch demo v1.0.0`。
9. 点 **Bind** → 标签从 `not bound` 变 **`bound`**。

### 2.4 建连接器
10. 到 **`3 · Downstream`** → 展开 **Add connector**，填：
    - Connector name：`Local echo (auto)`
    - Connector base URL：`http://127.0.0.1:18080`
    - Connector path：`/hooks/smart-edit`
    - Connector auth：`No auth`（spec / custom fields 留空）
11. 点 **Save connector** → 上方出现 `Target: Local echo (auto) · http://127.0.0.1:18080`。

### 2.5 建规则（默认 shadow）
12. 切到 **Rules** 页签 → **New rule**：
    - Rule name：`Guarantee → ERP`
    - Rule template：`Auto dispatch demo`
    - Rule connector：`Local echo (auto)`
    - Rule mode：保持 **`Shadow (record only)`**
13. 点 **Save rule** → 提示 `Rule saved. New rules stay in shadow until you raise the tier.`
14. 点规则行的 **Dry-run on this document** → 出现 `POST http://127.0.0.1:18080/hooks/smart-edit` 和
    `would_send` 里的 `values`（`amount: USD 250,000.00`），**下游没有收到请求**。

---

## 3. 第一轮：终审后只记录（Shadow，不外发）

1. **Sign out** → applicant 登录。
2. 底部点 **Start editing** → 点 **Submit new version**。
3. 对话框 `Submit for approval` 显示 `Bank Operations — First Approver` / `Compliance — Second Approver`
   → 点 **Submit for approval**。
   → 文档顶部变 **Pending first approval**，编辑器变只读。
4. **Sign out** → bankops 登录 → 顶部 **Approval** → 页签 **First approval** → 点待办记录 → 右下 **Approve**。
   → 状态变 **Pending second approval**。
5. **Sign out** → compliance 登录 → **Approval** → 页签 **Second approval** → 选记录 → **Approve**。
   → 状态 **Approved**。
6. 跑一次 worker（见第 0 步；常驻的话等 5–10 秒）。
7. **Sign out** → bankops 登录 → Automation → **Runs**：
   - 顶部：`Automatic sending is enabled globally …`
   - 交付徽标：**`Delivery: Shadowed`**
   - 列表：`Shadowed · Local echo (auto) · Guarantee → ERP · shadow · required`
   - **没有** Release/Retry/Cancel 按钮
8. 回到 **Automate → Recent dispatches**：**没有新回执**（阴影档不写回执）。

---

## 4. 第二轮：升档后真实发送

> `Approved` 是终态、文档永久只读，所以复测必须先重置文档（页面外的一步）。

1. 服务器执行（重建 `demo-document`，会清掉该文档上一轮的自动投递记录）：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py'
```

2. 浏览器 **F5**。bankops 登录 → Automation → Automate → **重新 Bind**
   （`Document type` 选 `Auto dispatch demo` → **Bind**）。重置后绑定会丢，必须重绑。
3. 在 **Rules** 里把 `Tier for Guarantee → ERP` 从 `Shadow` 改为 **`Auto send`**。
4. applicant 登录 → **Start editing** → 重新粘贴样例 → **Submit new version → Submit for approval**。
5. bankops → **Approval → First approval → Approve**；compliance → **Second approval → Approve**。
6. 跑 worker（或等常驻 unit）。
7. bankops → Automation → **Runs**：
   - 交付徽标 **`Delivery: Sent`**
   - 列表 `Sent`；点 **Details** → 时间线 `queued → sending → sent`
8. **Automate → Recent dispatches**：新增 `succeeded · 200 · …ms` + echo 响应摘录。
9. 服务器 echo 终端/日志出现 `POST /hooks/smart-edit`。

---

## 5. 第三轮：needs_review 人工放行

1. **Rules** 档位改 **`Needs review`**。
2. 重置文档 + 重新 Bind（同第 4 步）→ applicant 提交 → 一审 → 二审 → 跑 worker。
3. **Runs**：`Delivery: Needs review`，该行出现 **Release / Cancel**，下游仍未收到。
4. 点 **Release** → 变 `Queued`；再跑一次 worker → `Sent`，下游只收到一次。

---

## 6. 两个负向验证（可选，各 1 分钟）

- **规则暂停**：Rules → **Pause** → 重走终审 + worker → Runs 显示
  `Delivery: Not configured` + `No enabled rule matches this template…`。
- **未绑定**：重置文档后**不要 Bind** → 直接终审 + worker → Runs 显示
  `No template binding, so automatic delivery is skipped.`。
- **kill switch**（服务器改 `.env` 的 `SMART_EDIT_AUTOMATION_AUTO_SEND=0` 并重启 `smart-edit` 与
  `smart-edit-automation`）：Runs 顶部横幅变红，规则仍是 `Auto send` 但结果是 `Shadowed`。

---

## 两个页面使用小贴士

- **Runs 不自动轮询**：worker 跑完后，切到别的页签再切回 **Runs**（或 F5）才会刷新。
- **合规角色**能看到 Automation 但只能读（没有 Release/Retry/Cancel）；**applicant 看不到 Automation 标签**——这是权限收口的预期结果。

如果某一步和上面不一致，`DEMO_auto_dispatch.md` 的 §9 排错表按“现象 → 原因/处理”列出了常见情况（最常见的是：忘 Bind、worker 没启动、连接器主机不在白名单）。