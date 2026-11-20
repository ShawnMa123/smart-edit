# smart-edit 演示手册（下周 Demo 用）

> 一句话：把客户材料变成内部系统可用的标准文件，并在生成过程中做**格式 / 业务要件 / 法规与合规**三层校验；
> 每一条结论都能指回原文，查不到的会明确说"没查到"，而不是"没问题"。

| 项 | 值 |
|---|---|
| 演示地址 | **http://59.110.213.187:8082/** |
| 演示账号 | `applicant@atlas-trade.test` / `Applicant!2026`（主号）<br>`bankops@atlas-trade.test` / `BankOps!2026`（一审）<br>`compliance@atlas-trade.test` / `Compliance!2026`（二审）<br>`admin@atlas-trade.test` / `AtlasAdmin!2026`（管理员） |
| 建议时长 | 12–15 分钟（主流程 10 分钟 + Q&A） |
| 浏览器 | Chrome / Edge，宽度 ≥ 1400px（右侧助手面板才完整展开） |
| 演示文档 | 站点只有一份文档 `demo-document`，**粘贴即替换**；恢复命令见 §5.4 |

## 0. 一页速览：要展示的 5 件事

1. **法规风险扫描**：一份"武器出口到伊朗 + 规避制裁"的合同 → `Gate: Blocked`，4 条风险，锚点指回原文。
2. **法规证据 + 大模型综合**：一份中文独立保函 → 确定性措辞 + 《司法解释》第一/第三条的法条卡片。
3. **业务要件审计**：标准保函文本 → 57 项检查、`ratio 0.649`、唯一一条 blocking finding（开立日期在过去）。
4. **知识问答**：中文问题 → 5 条 claims / 5 条引用（法规语料），支持联网开关。
5. **双人审批 + 留痕**：applicant 提交 → bankops 一审 → compliance 二审；活动流水与功能权限。

---

## 1. 演示前检查（T-1 天 / 开场前 10 分钟）

### 1.1 服务健康（30 秒）

```bash
curl -s http://59.110.213.187:8082/health
# 期望：{"status":"ok","auth_mode":"pg"}

curl -s -o /dev/null -w '%{http_code}\n' http://59.110.213.187:8082/
# 期望：200
```

### 1.2 登录 + 能力探测（1 分钟）

浏览器打开站点 → 用 applicant 登录 → 右侧面板依次点开 4 个标签页（`Audit` / `Knowledge` / `Automation` / `Legal`），
确认没有红色错误提示。`Legal → Document check` 应显示 `Draft rev N · xxxx…`。

### 1.3 依赖状态（1 分钟）

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 '
  systemctl is-active smart-edit nginx
  firewall-cmd --list-ports
  curl -s -m 3 http://127.0.0.1:8080/health | head -c 200
'
# 期望：active / active；8080 8082；Mercatoria {"status":"ready",...}
```

### 1.4 模型额度与网络（1 分钟）

知识问答和法规扫描的"综合"这一步会调用豆包（Ark）。开场前**各跑一次**（§3.5、§3.2），确认不是配额/网络问题：

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'journalctl -u smart-edit -n 30 --no-pager | grep -Ei "error|timeout|401|403" | tail -5'
```

### 1.5 备份演示数据（推荐，10 秒）

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 '
  cd /opt/smart-edit && cp data/host.db data/host.db.demo-bak && ls -lh data/'
```

### 1.6 把演示文档恢复成"干净起点"（10 秒）

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py >/dev/null && echo restored'
```

> 该脚本会把 5 个演示账号的密码重置为本文档里的值，并把 `demo-document` 还原为
> "Demand Guarantee Application"（188 字，rev 1）。不会清空其他数据（除非加 `--reset`）。

---

## 2. 界面地图（10 秒认路）

```text
顶栏：S smart-edit | Activity | Approval | People | Inbox | Developer | Organisation ▾ | 用户 | Sign out
左栏（模块）：Document · Versions · Approval · Comments · People · Developer
中间：文档编辑器（Tiptap）+ 工具栏（样式 / Import file / Comments / 版本 / 提交）
右侧助手面板：Audit | Knowledge | Automation | Legal
底部状态：draft rev N · 保存状态 · 字数 · 版本数与锁信息
```

- 右侧四个标签页就是"四类能力"：**规则审计**（要件/规则）、**知识问答**（法规/内部语料/联网）、
  **自动化**（演示占位）、**法规与合规**（本文重点）。
- 编辑器是唯一文档；所有扫描/审计都读**当前草稿**，不读别处。
- 编辑器只读时先点 **Start editing**（拿编辑锁），否则粘贴不进去。

---

## 3. 15 分钟主流程（分镜脚本）

### 3.1 开场：登录与工作台（1 分钟）

**操作**：登录 applicant → 看到编辑器与右侧面板。

**台词**：

> 这是一份保函草稿。左边是业务要编辑的原文，右边是我们把"格式、业务要件、法规与合规"三类检查
> 放到同一处。所有检查都读**当前这份草稿**，结论必须能指回原文——这是这个产品最核心的约束。

**指一下**：顶部组织/角色、底部 `draft rev N`（说明每次保存都会 bump revision，后面的扫描会 pin 住它）。

---

### 3.2 核心演示：合规风险扫描（4 分钟）★

**操作**

1. 编辑器内 `Cmd/Ctrl+A` 全选 → 粘贴 §4.1 的**制裁样例**（中/英各一份）。
2. 等约 2 秒，右侧 `Legal → Document check` 顶部出现 `Draft rev 2 · …`。
3. 点 **Scan document**（约 3–10 秒，进度：`Splitting → Running deterministic checks → Checking statute evidence`）。

**预期（线上实测）**

```text
Gate: Blocked            Planned 12 · assessed 10 (83%) · 1 clauses
Critical  Blocks         Sensitive goods destined for a sanctioned country
                         In the draft: 弹药 / 导弹 / 军用无人机 / 伊朗   → 4 个 Jump to clause
Critical  Needs review   Export-controlled goods without a stated licence
Critical  Needs review   Comprehensively sanctioned destination referenced
Warning   Needs review   Circumvention wording detected
```

**台词**：

> 这份合同要"从美国出口军用无人机部件、导弹备件和弹药到伊朗"，还写了"第三国现金支付、经第三国转运以规避制裁审查"。
> 系统不是"看到伊朗就报警"，而是做了组合判断：**受控货物 + 全面制裁目的地 = 硬阻断**；
> 单独出现受控货物或规避措辞，只会转人工复核。每条都能点 `Jump to clause` 回到原句。

4. 点一条 **Jump to clause**（光标跳到对应段落），再指一下 `In the draft (4)` 的引用块。
5. 勾选 **Use web search for clauses the corpus does not cover** → 再点 **Scan again**：
   多一条 `Info · Web sources need a human check`，带真实链接并标注 `Unverified web source`。

**台词（联网那一步）**：

> 联网是**用户选择**，默认关闭。打开后只把"未覆盖条款的标题"发出去，结果一律标记为未验证，
> 且永远不会单独构成阻断。旁边这句 "the corpus did not cover this clause" 就是它在说"我查了，但不敢当结论"。

**兜底**：若模型/法规服务不可用，页面仍会显示确定性的三条 Critical（`basis: rule`），
并由 gate 给出 `unchecked_units`；照常讲"没查到的部分会明确说没查到"。

---

### 3.3 同一面板的另外两份样例（3 分钟）

**A. 法规证据 + 大模型综合（中文保函，§4.2）**

预期：`Gate: Needs human review`、`Planned 21 · assessed 20 (95%)`，4 条 finding：

| 依据 | Finding |
|---|---|
| rule | Unconditional payment wording（锚点 `无条件付款`） |
| rule | Automatic extension（锚点 `自动展期`） |
| statute | 独立保函未载明据以付款的单据要求…（引《…规定》**第一条/第三条**） |
| statute | 独立保函付款单据要求表述不完整（2 条证据） |

台词：> 这两条法条结论不是模型背出来的：蓝色卡片是 RAGFlow 检索到的条文（条号/法域/生效日/chunk id 都在），
> 模型只能引用这些证据 id，不能自己加严重度，也不能 hard block。

**B. 硬阻断（英文，§4.3）**

预期：`Gate: Blocked`、3 条 `Critical/hard_block`（金额缺失、币种缺失、失效日早于开立日）+ 1 条 Warning（自动展期）。

台词：> 这类"缺字段/日期倒置"完全不依赖模型，是确定性规则；所以即使断网也能给结论。

---

### 3.4 业务要件审计（Rule audit，3 分钟）

**操作**

1. 粘贴 §4.4 的**标准保函**（`fixtures/llm/sample_document.txt`，BG-2026-00417）。
2. 右侧 `Audit` 标签 → 在 **Customer template** 输入框填 `adidas-guarantee` → 点 **Run spec audit**（约 1 秒）。

**预期（线上实测）**

```text
verification.extraction: deterministic · guarantee-default@1.1.0 · fields_found 8 / missing 1
verification.audit:      planned 57 · pass 36 · finding 1 · not_applicable 19 · unable_to_assess 1
coverage.ratio:          0.649          verdict: warn
finding:                 CO-ISSUE-NOT-PAST（Critical/blocking）
                         "Issue date must not be earlier than the audit date" · evidence 2026-03-12
```

台词：>

> 57 项检查里，36 项通过、19 项不适用（这份文档没有相应条款）、1 项无法评估、**1 项阻断**：
> 开立日期 2026-03-12 早于今天，违反公司政策。注意它把"不适用"和"没查成"分开计数——
> 这正是"没发现问题"与"没检查"在数据结构上可区分。

**变体（想演"干净通过"）**：把 `Issue Date` 改成 `01/12/26`（DMY → 2026-12-01），
则 0 finding、`verdict` 变成可提交状态。

---

### 3.5 知识问答（2 分钟）

**操作**：`Knowledge` 标签 → 点第一条建议问题 **“独立保函必须载明哪些事项才有效？”**（约 11 秒）。

**预期（线上实测）**

```text
outcome: answered · support_level: qualified · claims 5 · citations 5
retrieval: statute ok（hits 5）· local 参与 · limitations 说明"仅覆盖最高院司法解释"
```

台词：>

> 问题的路由是固定的：先查法规语料（RAGFlow/Mercatoria），必要时豆包总结；只有语料零结果才自动联网。
> 引用可以点开看原文，限定说明也一并展示——它不会把"只查到部分依据"说成"完整答案"。

**诚实对照（推荐顺带展示）**：点英文建议问题 “What does URDG 758 article 20 require for claims?”，
会得到 `insufficient_evidence`：语料里没有 URDG 758 原文。**这就是卖点，不是故障**——
系统会明确说"没有可用证据"，而不是编一个条款。

---

### 3.6 提交与双人审批（2 分钟）

**操作**

1. applicant：编辑器工具栏 **Submit new version** → 填说明 → **Submit for approval**。
2. 退出 → 用 `bankops` 登录 → 顶部 **Approval** → 标签 **First approval** → 选记录 → **Approve**。
3. 退出 → 用 `compliance` 登录 → **Approval** → **Second approval** → **Approve**。
4. 回到 applicant：文档变为只读（`Approved`），Versions/Approval 面板能看到状态与快照。

**台词**：>

> 提交的是**快照**（revision + sha），审批人看到的就是提交时的文本；Approver 之间职责分离，
> 每次决定都写活动流水。审批期间文档锁定只读，避免"批的和改的不是一份东西"。

---

### 3.7 可选：组织、权限、API（1 分钟）

- `People`：成员/部门/邀请（PG 身份，角色：Applicant / Bank Ops（一审）/ Compliance（二审）/ Auditor / Org admin）。
- `Developer`：API keys、请求日志、7 天用量（用 API key 调 `/runs` 时记录）。
- `Activity`：谁在什么时候做了什么（审计轨迹）。

台词：> 这层是"谁能看、谁能改、谁批过"的底座；所有 AI 结论都挂在组织/文档权限下，不绕过授权。

---

## 4. 样例文档（直接粘贴；仓库里也有）

所有样例在 `fixtures/legal-samples/`（另有 `README.md` 写了各自的预期）。
粘贴方式：点编辑器 → `Cmd/Ctrl+A` → 粘贴 → 等 2 秒自动保存（`Draft rev` 变化）→ 扫描/审计。

### 4.1 制裁与出口管制（**核心样例**）

中文版（推荐）：

```text
出口合同

卖方：Northbridge Arms Trading LLC（美国）
买方：Sepahan Logistics Co.（伊朗）
目的地：伊朗德黑兰
货物：军用无人机部件、导弹备件及弹药 120 套
合同金额：USD 4,800,000.00
适用法律：新加坡
付款：第三国现金支付，经第三国转运以规避制裁审查
```

英文版：`fixtures/legal-samples/sanctions-export.txt`

```text
EXPORT AGREEMENT
Seller: Northbridge Arms Trading LLC (United States)
Buyer: Sepahan Logistics Co. (Iran)
Destination: Tehran, Iran
Goods: 120 units of military-grade drone components, guided missile spare parts and ammunition
Contract value: USD 4,800,000.00
Governing law: Singapore
Payment: cash in a third country, shipment routed via a third country to avoid sanctions screening
```

**预期**：`Gate: Blocked`、`Planned 12 · assessed 10 (83%)`、4 条 finding（3 Critical），
第一条带 4 个草稿锚点（货物 3 处 + 目的地 1 处）。

### 4.2 中文独立保函（法规证据 + 综合）

```text
独立保函

申请人：上海远洋贸易有限公司
受益人：Meridian Exports Pte Ltd
保函金额：USD 250,000.00
开立日期：2026-01-10
失效日期：2027-06-30
适用规则：URDG 758
管辖：新加坡

第一条 付款
本保函为无条件付款承诺，受益人仅需提交书面索赔即可获得付款。

第二条 展期
本保函到期后自动展期一年，无需受益人同意。
```

**预期**：`Gate: Needs human review`、`Planned 21 · assessed 20 (95%)`、2 条 rule + 2 条 statute。

### 4.3 硬阻断（缺金额 / 币种 / 日期倒置）

```text
DRAFT PAYMENT UNDERTAKING
Applicant: Shanghai Ocean Trading Co., Ltd.
Beneficiary: Meridian Exports Pte Ltd
Issue date: 2027-01-10
Expiry date: 2026-06-30
Governing rules: URDG 758
Jurisdiction: Singapore
Claim documents: written demand and statement of breach

1. Payment
We undertake to pay against your written demand.

2. Extension
This undertaking shall be automatically extended for one year unless we give notice.
```

**预期**：`Gate: Blocked`、`Planned 19 · assessed 17 (89.5%)`、3 条 Critical/hard_block + 1 条 Warning。

### 4.4 标准保函（Rule audit 用；= `fixtures/llm/sample_document.txt`）

```text
DEMAND GUARANTEE
Guarantee No: BG-2026-00417
Applicant: Alpha Tech Pte Ltd
Beneficiary: Beta Construction Ltd
Amount: USD 500,000.00
Currency: USD
Issue Date: 12/03/26
Expiry Date: 12/03/27
Governing Rules: URDG 758

This guarantee is payable on first written demand.
```

**预期（Audit，template `adidas-guarantee`）**：`planned 57`、`pass 36`、`finding 1`、
`not_applicable 19`、`unable_to_assess 1`、`ratio 0.649`、`verdict warn`；
唯一 finding 为 `CO-ISSUE-NOT-PAST`（开立日期 2026-03-12 早于审计日）。

### 4.5 对照组（证明不误报）

```text
SOFTWARE LICENCE AGREEMENT
Supplier: Northwind Software Ltd (Singapore)
Customer: Harbourview Logistics Pte Ltd (Singapore)
Contract value: USD 25,000.00
Governing law: Singapore
The supplier grants a non-exclusive licence for warehouse management software, delivered electronically.
Payment is by bank transfer within 30 days of invoice.
```

**预期**：`Planned 19 · assessed 17 (89.5%)`；合规层 4 个单元为 `not_applicable` / `pass`，无合规 finding；
英文条款的法规腿仍会 `unable_to_assess`（`low_confidence`）——这正是"没查到 ≠ 没问题"。

### 4.6 导入文件演示（可选）

工具栏 **Import file** 支持 `.pdf / .docx / .png / .jpg`（服务端解析）。仓库里现成的：
`fixtures/imports/guarantee.docx`、`guarantee-and-standby-letters-of-credit-wording.pdf`、`scan.png`。
注意：**Import 是"另起一个 run 去解析"，不会自动替换编辑器正文**；正文演示仍以粘贴为主。

---

## 5. 运行说明（运维手册）

### 5.1 架构

```text
浏览器 :8082 → nginx ─┬─ /        → /opt/smart-edit/web/dist（Vite 构建产物，SPA）
                      ├─ /api/*   → 127.0.0.1:8000（uvicorn，去掉 /api 前缀）
                      └─ /health  → 127.0.0.1:8000/health
后端 systemd：smart-edit（单 worker；run 状态在进程内）
外部依赖：阿里云 RDS（账号/组织）、Mercatoria :8080（RAGFlow 法规检索）、豆包 Ark（综合/联网）
```

### 5.2 部署 / 更新

```bash
# 本机（仓库根目录）
./deploy/deploy.sh                 # 构建前端 + 同步 + 远端 pip/systemd/nginx + 外网自检
./deploy/deploy.sh --no-build      # 只改了后端时（跳过 npm build）
./deploy/deploy.sh --remote-only   # 只重装 systemd/nginx（改了配置）
```

### 5.3 常用命令

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187

systemctl status smart-edit            # 后端状态
journalctl -u smart-edit -f            # 后端日志（含 request_id）
journalctl -u smart-edit --since "10 min ago" | grep -Ei "error|timeout|failed"
systemctl restart smart-edit           # 重启后端（会清空进程内 run 状态）
systemctl reload nginx                 # 改 nginx 配置后
tail -f /var/log/nginx/smart-edit.error.log
firewall-cmd --list-ports              # 期望 8080/tcp 8082/tcp
ss -lntp | grep -E ':(8000|8082)\b'
```

### 5.4 演示数据与恢复

| 数据 | 位置 | 说明 |
|---|---|---|
| 文档/草稿/审批/活动 | `/opt/smart-edit/data/host.db`（SQLite） | 唯一文档 `demo-document` |
| 账号/组织/会话 | 阿里云 RDS `team04`（PG） | 由 `scripts/seed_identity_users.py` 维护 |
| 法规报告 | `/opt/smart-edit/runs/legal.db` | 扫描报告（按 workspace 校验） |
| 助手会话/语料 | `/opt/smart-edit/data/assistant.db` | 知识问答 |
| run 产物/上传件 | `/opt/smart-edit/runs/` | 进程内 run 重启即失效 |

```bash
# 恢复演示文档 + 账号密码（最常用）
cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py

# 演示前备份 / 演示后还原文档库
cp data/host.db data/host.db.bak
cp data/host.db.bak data/host.db && systemctl restart smart-edit
```

> 注意：`seed_identity_users.py --reset` 会 **truncate** 身份相关表（用户/组织/会话）；只在需要"完全重来"时用。

### 5.5 回滚

```bash
# 代码回滚：本机 git checkout <上一个 commit> 后 ./deploy/deploy.sh
# 配置回滚：/opt/smart-edit/.env 由 deploy/env.ecs 覆盖，改回后 ./deploy/deploy.sh --remote-only
# 数据回滚：按 §5.4 还原 host.db（legal.db / assistant.db 可直接删除，重启自动重建）
```

---

## 6. 环境变量与依赖（当前线上状态）

`.env` 在服务器 `/opt/smart-edit/.env`（600，不入库）；模板见 `deploy/env.ecs.example`。

| 变量 | 线上值/默认 | 作用 |
|---|---|---|
| `SMART_EDIT_AUTH_MODE` | `pg` | 真实账号（RDS），`fake` 仅本地演示 |
| `SMART_EDIT_DATABASE_URL` | RDS 内网地址 | 账号/组织/会话 |
| `SMART_EDIT_ASSISTANT_MODEL` | `doubao:doubao-seed-2-1-lite-260915` | 综合/联网用的模型 |
| `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED` | `1` | 允许调用已批准模型（不配 → 所有综合步骤 `unavailable`） |
| `SMART_EDIT_ASSISTANT_GENERAL_WEB` | `1` | 允许"模型自带联网"通道 |
| `SMART_EDIT_STATUTE` | `1` | 启用法规语料 |
| `MERCATORIA_BASE_URL` | `http://127.0.0.1:8080` | RAGFlow/Mercatoria（同机 docker） |
| `SMART_EDIT_LLM` | `fixture:fixtures/llm/extract_sample.json` | **Rule audit 的抽取兜底**；有 extraction profile 时走确定性抽取，不用它 |
| `SMART_EDIT_LEGAL_WEB_DEFAULT` | `0` | 合规扫描联网默认关（用户勾选优先） |
| `SMART_EDIT_LEGAL_MAX_CLAUSES` | `12` | 单次扫描条款上限（超出标 `truncated`） |
| `SMART_EDIT_LEGAL_SCAN_DEADLINE` | `90` | 扫描总预算（秒） |
| `SMART_EDIT_HOST_DB` / `SMART_EDIT_ASSISTANT_DB` | `/opt/smart-edit/data/*.db` | 文档库 / 助手库 |

依赖服务自检：

```bash
curl -s http://127.0.0.1:8080/health                      # Mercatoria
curl -s http://59.110.213.187:8082/assistant/capabilities # 需要登录 cookie；看 statute.enabled/reachable
```

---

## 7. 诚实边界（被问到时照实说）

### 7.1 真实链路（可以现场验证）

- 账号/组织/部门/角色/权限：PostgreSQL + argon2id + HttpOnly 会话。
- 文档：草稿、编辑锁（fencing token）、快照、版本、双人审批、活动流水。
- 法规检索：RAGFlow/Mercatoria（线上 143 份文档 / 11,562 chunks / 7 个法域）。
- 大模型：豆包 Ark（只做"在给定证据内归纳"，不产出无证据结论）。
- 合规扫描：词表 + 组合判定（确定性）+ 模型补充（受证据约束）+ 覆盖率/闸门。
- 报告持久化：`runs/legal.db`（按 workspace 校验）。

### 7.2 演示占位（不要过度承诺）

| 项 | 状态 |
|---|---|
| `Automation` 标签 | fixture-only（脚本化演示），不是生产自动化 |
| `Comments` | 占位（无评论服务） |
| `Export` | 不可用（产品明确标注） |
| `adidas-guarantee` 模板 | **synthetic**（POC 录制，不是真实客户合同；报告里会写） |
| 规则审计的抽取 | 有 extraction profile 时是确定性定位；没有 profile 时才退回 `SMART_EDIT_LLM` fixture |
| 文档宿主 | 本地 SQLite/演示适配器；不是已批准的银行内容管理系统 |

### 7.3 明确"不是"

- **不是法务意见**：所有 finding 都标注"red flag / 提示"，最终结论要人。
- **不是筛查服务**：没有接入 OFAC SDN / BIS Entity List / EU / UN 名单，也没有货物分类（ECCN/USML）与许可判断。
- **不是全语料**：语料以 CN/EU/INT/US/WTO 的贸易与海关规则为主；英文条款常 `low_confidence`，系统会如实说"没查到"。
- **不是多租户 SaaS**：演示是单组织 `ws_demo_01`。

### 7.4 三句可以反复用的"诚实口径"

1. "**没查到 ≠ 没问题**：报告里 `assessed / planned`、`unchecked_units`、`low_confidence` 就是这件事。"
2. "**模型不能造证据**：它只能引用检索到的 id，且不能把严重度提到 `Critical` 或直接 hard block。"
3. "**出网是用户的决定**：联网默认关，打开也只发未覆盖条款的标题，结果标 `unverified`。"

---

## 8. 故障排查（现场速查）

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面空白 / JS 404 | `web/dist` 与远端不一致 | 本机 `./deploy/deploy.sh`（会重建前端） |
| 登录 401、所有接口 401 | 会话 cookie 未带上 / 已过期 | 重新登录；确认用 `http://…:8082` 而不是 https |
| 登录 401 且密码正确 | 账号表被重置 | `scripts/seed_identity_users.py` |
| 编辑器不能输入 | 只读（无锁/审批中/角色不允许） | 点 **Start editing**；若是审批中，属预期只读 |
| 扫描一直 `Checking statute evidence` | 模型/检索慢或超时 | 等 90s 预算；`journalctl -u smart-edit -f` 看 `timeout`；必要时重扫 |
| 所有条款 `composer_unavailable` | 模型未配置或未批准 | 检查 `.env` 的 `SMART_EDIT_ASSISTANT_*`，重启服务 |
| 大量 `uncovered:*` / `low_confidence` | 语料不覆盖该法域/主题 | 换中文样例；或把这句当"诚实边界"讲 |
| 点 Scan 立刻 `stale_snapshot` | 粘贴后自动保存还没完成 | 等 `saved` 再点；或直接重扫 |
| `Gate: Blocked` 但不是你想演的 | 样例本身有硬阻断 | 用 §4.5 对照组，或按 §3.4 变体改日期 |
| 8082 打不开（外网） | 安全组 / 主机 firewalld | 控制台放行 + `firewall-cmd --list-ports` 含 8082 |
| 重启后旧 run 报 `unknown_run` | run 状态是进程内的 | 重新创建 run（属设计行为） |
| 知识问答 `needs_clarification` | 问题超出语料 | 换成 §3.5 的中文问题；或演示"它不编" |

---

## 9. Q&A 预演（大概率会被问）

**Q1. 这些结论是模型编的吗？**
不是单一模型输出。三层：① 确定性规则（缺字段/日期/词表组合）不依赖模型；② 法规结论必须来自
RAGFlow 检索到的 chunk（条号/法域/生效日/chunk id 可复核）；③ 模型只能在给定证据内归纳，
未知证据 id 会被丢弃、`quote` 必须是原文子串、严重度上限 `Warning`、不能 hard block。

**Q2. 为什么英文条款说"无法评估"？**
法规语料当前覆盖 CN/EU/INT/US/WTO 的贸易与海关规则，英文保函条款常被判 `low_confidence`。
系统按设计不拿弱证据下结论，所以显示 `unable_to_assess` 并把它计入 `unchecked_units`。

**Q3. 制裁名单从哪来？**
当前是**策展词表 + 组合判定**（目的地两级 × 受控货物 11 类 × 跨境渠道 × 规避措辞），
不是 OFAC/BIS 名单。名单快照与货物分类是下一步（`openspec` tasks 9.7）。

**Q4. 会不会误报？**
不是"看到关键词就报"：只有"受控货物 × 全面制裁目的地"才 `hard_block`；单独受控货物或规避措辞是
`human_review`。§4.5 的软件许可合同零合规 finding，就是给客户看的对照组。

**Q5. 文档会不会外发？**
默认不出网。模型调用只发**单个条款**（≤1200 字）+ 证据摘录，先走脱敏（敏感值变 `[redacted]`）；
只有用户勾选联网才发出，且只发未覆盖条款的标题；报告记录 `web_requested / web_used / web_calls`。

**Q6. 延迟和成本？**
合规扫描 3–20 秒（≤12 条款），知识问答约 10 秒，确定性检查约 1 秒。
控制手段：`thinking` 默认关、每条条款最多 5 条证据、联网默认关、条款上限与 90s 预算。

**Q7. 能接我们自己的规则/名单/接口吗？**
可以：规则包 `app/rules/bundles/*.yaml`（带 test vectors，`python -m app.rules.doctor` 门禁）、
抽取 profile JSON、脱敏白名单 `knowledge.sample.json`、合规词表（后续做成部署可维护的 JSON）。

**Q8. 怎么证明"看过了/没看过"？**
报告里 `coverage_summary`（planned/assessed/ratio）、每条 check 的 `reason_codes`、
`retrieval.queries/hits/layers`、finding 的 `document_anchors`（可回跳）、快照 `revision + sha256`；
服务端每次请求有 `request_id`，动作进活动流水。

**Q9. 多人协作/权限？**
PG 账号 + 组织/部门/角色；文档编辑锁（fencing token）防并发覆盖；审批职责分离（一审/二审）；
API key 与请求日志在 `Developer`。

**Q10. 下一步做什么？**
① 扫描 gate 接入提交按钮（`blocked` 直接禁用提交）；② denied-party 名单与货物分类；
③ 合规词表/规则运维化（不改代码）；④ 多实例部署时把报告迁到 PG；⑤ 用样本集做误报/漏报评测。

---

## 10. 附录

### 10.1 一条命令自检（不打开浏览器）

```bash
B=http://59.110.213.187:8082/api
curl -s -c /tmp/cj -o /dev/null -X POST $B/auth/login \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  -d '{"email":"applicant@atlas-trade.test","password":"Applicant!2026"}'
curl -s -b /tmp/cj http://59.110.213.187:8082/health
RID=$(curl -s -b /tmp/cj -X POST $B/legal/reviews \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  -d '{"workspace_id":"ws_demo_01","document_id":"demo-document","scope":"document",
       "modes":["deterministic","legal"],"web_search":false}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
for i in $(seq 1 30); do sleep 2; ST=$(curl -s -b /tmp/cj $B/legal/runs/$RID | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])'); echo "$ST"; case $ST in succeeded|failed) break;; esac; done
```

### 10.2 文件地图（需要改东西时看这里）

```text
app/api/legal.py                  /legal/reviews、/legal/runs/{id}、/legal/reports/{id}
app/legal_review/contracts.py     契约（scope、document_anchors、coverage_summary、gate）
app/legal_review/document.py      条款切分 + 锚点
app/legal_review/checks.py        要素 / 日期 / 高风险措辞（确定性）
app/legal_review/compliance.py    制裁 / 出口管制 / 规避（词表 + 组合判定）
app/legal_review/scan.py          计划 → 检索 → 综合 → 覆盖率 → 闸门
app/legal_review/compose.py       豆包证据约束综合 + 联网补检
app/legal_review/store.py         SQLite 报告/幂等
app/configs/extraction/*.json     抽取 profile（guarantee-default 1.1.0）
app/configs/knowledge.sample.json 建议问题 / 管辖域 / 脱敏 / 查询扩展
app/templates/adidas-guarantee.yaml  审计模板（synthetic）
web/src/components/LegalPanel.tsx    Document check UI
web/src/rich/useRichEditor.ts        编辑器（含 focusBlock 跳转）
fixtures/legal-samples/              演示样例 + README（预期）
deploy/                              部署脚本 / systemd / nginx / env 模板
```

### 10.3 规格索引（`openspec/`）

```text
legal-document-risk-scan   合规扫描（含制裁/出口管制层、闸门、覆盖率）
legal-review               L1 法规问答 + 确定性规则
knowledge-statute-chat     法规助手两段式生成
knowledge-general-web      联网通道与引用规则
document-submission-approval / document-host-foundation   审批与文档宿主
```

`openspec list` 可看全部；`openspec validate <change> --strict` 校验。

### 10.4 两套时间预算

| 版本 | 内容 | 时长 |
|---|---|---|
| 8 分钟 | 3.1 开场 → 3.2 制裁扫描（重点） → 3.4 规则审计 → 3.5 知识问答 | 8 分钟 |
| 15 分钟 | 上述 + 3.3 法条样例 + 3.6 双人审批 + 3.7 组织/API | 15 分钟 |

### 10.5 一页 Cheat Sheet

```text
登录：applicant@atlas-trade.test / Applicant!2026
扫描：右侧 Legal → Document check → Scan document
审计：右侧 Audit → Customer template 填 adidas-guarantee → Run spec audit
问答：右侧 Knowledge → 点“独立保函必须载明哪些事项才有效？”
审批：bankops → Approval/First approval → Approve；compliance → Second approval → Approve
恢复：ssh team04_ecs → cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py
样例：fixtures/legal-samples/{sanctions-export-zh,statute-zh,hard-block,clean}.txt
```