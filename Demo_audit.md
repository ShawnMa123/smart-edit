# Rule Audit 演示指南（`Run spec audit`）

> 适用：`agent-audit` / `verification`（Rule audit 标签）
> 环境：**http://59.110.213.187:8082/**（fixture/deterministic 模型已配置）
> 建议时长：**6–8 分钟**（主流程 3 分钟 + 3 个变体各 1 分钟）
> 推荐账号：`applicant@atlas-trade.test / Applicant!2026`（bankops / compliance / admin 也能运行）
>
> 关键点：**审计不会修改文档、不需要编辑锁**；它把“当前编辑器文本”冻结成快照 → `normalize` → `audit`，
> 报告绑定该快照的摘要。提交中/已批准的只读文档同样可以审计。

---

## 0. 60 秒速览

```text
applicant 登录 → Start editing → 粘贴样例保函 → Save（Saved to server）
右侧 AI assistant → 标签 `Rule audit`（短标签 Audit）
Customer template 填 `adidas-guarantee` → 点 `Run spec audit`
约 1 秒后：planned 57 · pass 36 · finding 1 · not_applicable 19 · unable 1 · ratio 0.649
唯一阻断：CO-ISSUE-NOT-PAST（Critical / hard_block）
改 Issue Date 为 01/12/26 → Save → `Re-audit current snapshot` → finding 0（但仍有 1 项 unable）
```

---

## 1. 这个功能做什么 / 不做什么

| 会检查（面板 `What this audit checks`） | 不会检查（`Not checked in this build`） |
|---|---|
| 必填字段是否出现（来自字段字典） | 语义一致性检查（RULE-02） |
| 值格式：金额、币种、日期顺序 | 客户/银行模板条款（RULE-03，本版只有模板包，不含 NLP 语义） |
| 字段长度上限与截断 | 监管覆盖与法域适用性（Requirements §9.2） |

面板会把 **`not_applicable`（不适用）**、**`needs_input`（没读到）**、**`unable_to_assess`（没查成）**
分开计数——这是“**没发现问题 ≠ 合规**”的落点。

---

## 2. 前置（30 秒）

1. 浏览器打开 **http://59.110.213.187:8082/**（Chrome，宽度 ≥ 1400px）。
2. **硬刷新** `Cmd/Ctrl+Shift+R`（确保拿到含本地 SHA-256 回退的前端包）。
3. 记一下两种抽取来源（面板会标明，不需要你选）：
   - **填了 Customer template** → `deterministic`（按模板的 extraction profile 读值）；
   - **没填** → `fixture`（ECS 用 `SMART_EDIT_LLM=fixture:…`，面板会显示 **Fixture-backed run** 横幅）。

> 审计要求正文非空。空正文会直接失败：`400 EMPTY_SUBMISSION`
> （界面显示 `Audit failed — no conclusion produced` + `Code EMPTY_SUBMISSION`）。

### 2.1 调试时用哪份文档？（bankops 也会遇到“只读”）

| 目的 | 用什么文档 |
|---|---|
| 只想跑审计、**不改文字** | 任意文档都行：`pending_first / pending_second / approved` 是只读，但**审计不需要编辑锁** |
| 需要改文字做变体 | ① 选一份 **`draft`** 文档（例如 `Trade application (spec demo)`），或 ② 在 `Approval → First approval` 对目标提交点 **Return**（填意见）→ 文档变 `returned` → 可编辑 |
| 想新建一份空白调试文档 | 文档头 **New document**（`bank_ops` 现在也有 `document.create` / `document.edit`）；新建后自动取得编辑锁，可直接粘贴样例并 **Save** |
| 多方轮流编辑同一份文本 | 编辑锁是**独占**的：一方保存/释放锁后另一方再 `Start editing`；提交后快照冻结，需 **Return** 才能继续改 |

> 看到 `This submitted version is read-only until it is returned or approved …`
> 表示这份文档**已提交**（对所有人冻结），不是权限问题：**Return** 或换一份 `draft` 即可编辑。

---

## 3. 准备样例文档（1 分钟）

用 **applicant** 登录：

1. 编辑器底部点 **Start editing**（取得编辑锁）。
2. `Cmd/Ctrl+A` → 粘贴下面的样例（同 `fixtures/llm/sample_document.txt`）：

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

3. 点底部 **Save**（或等 2 秒自动保存）→ 状态行出现 **Saved to server**。

> 任一账号都可以审计；bankops/compliance 打开这份文档时是只读，但 **Audit 仍可运行**（只读不影响快照）。

---

## 4. 主流程：第一次审计（推荐填模板）

1. 右侧 **AI assistant** → 顶部标签 **`Rule audit`**（短标签 `Audit`，chip `Full`）。
2. 初始空状态显示 **`Run a spec audit`** 与说明；下方是 **Customer template** 输入框（可选）。
3. 在 **Customer template** 填 **`adidas-guarantee`**。
4. 点 **`Run spec audit`**。
5. 运行中会看到：**`Fixed snapshot captured — running checks`**、`Auditing snapshot <digest>`、
   已用时（`x.xs`）与 **`Stop waiting`**。
   - `Stop waiting` **只停止本页等待**：服务端可能仍在跑，页面不会给结论。
6. 约 1 秒后出现结果。

### 预期结果（线上实测）

```text
Result chip:  Findings need review
指标条:       Planned 57 · Assessed 37 · Not applicable 19 · Needs input 0 · Hard blocks 1
Rule audit:   findings_present · 37 of 57 planned checks assessed · ratio 0.649
抽取来源:     deterministic · guarantee-default@1.1.0 · 8 fields found · 1 missing
模板:         Template could not be resolved — reason: no_applicable_template（见下方解释）
Gate:         No operation was asked about, so nothing is allowed
Audit findings (1):
  B-001 · Critical · hard_block · CO-ISSUE-NOT-PAST
  Issue date must not be earlier than the audit date
  Field: issue_date · Evidence: “2026-03-12”
  Blocks: start_approval, formal_export, handoff
```

**为什么模板显示“未解析”？**
`adidas-guarantee` 要求对手方字段 `beneficiary_name = Adidas AG`，而这份样例是 `Beta Construction Ltd`，
所以它**不猜**：`requested=true`、`no_applicable_template`，计划数从 63 降到 57（多一个 `TEMPLATE:resolution` 单元）。
这本身就是演示点：**模板不匹配时不会硬套**。

> 台词：这 57 项里 36 项通过、19 项不适用（文档没有对应条款）、1 项没查成（模板解析），
> **1 项阻断**：开立日期 2026-03-12 早于今天，违反公司政策。注意“没查到”与“通过”在数据里是分开的。

### 页面元素对照（结果页从上到下）

| 区块 | 你会看到 |
|---|---|
| 状态行 | `Findings need review` / `No findings in the checks that ran` / `Field checks did not run` |
| 指标 | Planned / Assessed / Not applicable / Needs input / Hard blocks |
| `Where the values came from` | 抽取来源、profile 版本、fields found/missing、audit date、冲突字段（如有） |
| `Gate` | 没有点名操作时明确写 “nothing is allowed”；点名时显示 decision + reasons |
| `Stages` | `extract / normalize / audit` 各自状态与原因（fixture 会写 `fixture:<file>`） |
| `Rule audit` | 计划/评估/覆盖率比例 + 每条 finding（严重度、field、blocked actions、rule id、method、evidence） |
| `Template` | 命中时显示 `adidas-guarantee v1.0.0 · synthetic: true · counterparty Adidas AG · packs …` |
| 字段表 | 每个字段的 Value / Status（Extracted、Inferred、Not found）/ Notes · source |
| 底部 | `No findings does not mean the document is compliant.` + 绑定快照摘要 |
---

## 5. 变体 A：干净通过（0 finding）

1. 把样例里的 `Issue Date: 12/03/26` 改成 **`Issue Date: 01/12/26`**（DMY → 2026-12-01）。
2. 点 **Save**（等 `Saved to server`）。
3. 回到 Audit → 点 **`Re-audit current snapshot`**（template 仍填 `adidas-guarantee`）。

### 预期（线上实测）

```text
Result:      No findings in the checks that ran
指标:        Planned 57 · Assessed 37 · Not applicable 19 · Needs input 0 · Hard blocks 0
Rule audit:  unable_to_assess · 37 of 57 assessed · ratio 0.649
说明:        仍有 1 项 unable_to_assess（模板解析那一个单元），所以结论不是“干净通过”
```

> 台词：**0 finding 不等于合规**。这里 `unable_to_assess` 仍为 1（模板未解析），
> 面板底部也固定写着 “No findings does not mean the document is compliant.”。

---

## 6. 变体 B：模板命中（对手方是 Adidas）

1. 把 `Beneficiary: Beta Construction Ltd` 改成 **`Beneficiary: Adidas AG`**。
2. **Save** → **`Re-audit current snapshot`**（template 仍填 `adidas-guarantee`）。

### 预期（线上实测）

```text
模板:        adidas-guarantee v1.0.0 · synthetic: true · counterparty Adidas AG · packs guarantee-core
指标:        Planned 63 · Assessed 42 · Not applicable 20 · Needs input 1 · Hard blocks 3
Rule audit:  findings_present · ratio 0.667
Audit findings (4):
  B-001 Critical hard_block  CO-ISSUE-NOT-PAST        Issue date must not be earlier than the audit date
  B-002 Critical hard_block  TEMPLATE:…payment-clause Required clause adidas-payment-clause is missing
  B-003 Critical hard_block  TEMPLATE:…law-clause     Controlled clause adidas-law-clause does not match its controlled text
  B-004 Warning  human_review TEMPLATE:…lawful-source  Declaration lawful-source is missing
```

演示点：

- 模板命中后计划数 **57 → 63**（3 字段期望 + 2 条款 + 1 声明）；
- `synthetic: true` 明示这是 POC 的合成模板，不是真实合同；
- `needs_input 1`：`origin_country` 不在 `fields.yaml`，模板从 `extra_fields` 读——**抽不到是“没读到”，不是“文档缺值”**；
- 条款判断三类：`required`（缺 → finding）、`controlled`（不一致 → finding）、`optional`（缺 → 不适用）。

---

## 7. 变体 C：不填模板（fixture 兜底）

1. 把 **Customer template** 清空。
2. 点 **`Run spec audit`**。

### 预期（线上实测）

```text
横幅:        Fixture-backed run
Stages:      extract — fixture:fixtures/llm/extract_sample.json
指标:        Planned 56 · Assessed 37 · Not applicable 19 · Needs input 0 · Hard blocks 1
Rule audit:  findings_present · ratio 0.661
```

> 台词：这条横幅是在说“候选值来自固定 fixture，**不是对当前文档的抽取**”，只用于检查流程；
> 想按文档真实取值，就填模板（走 deterministic profile）。

---

## 8. 负向场景（各 1 分钟，都是“诚实”卖点）

| 场景 | 操作 | 预期 |
|---|---|---|
| 空文档 | 新文档不输入内容 → Run spec audit | `Audit failed — no conclusion produced`，`Code EMPTY_SUBMISSION`；按钮变 `Run spec audit again` |
| 审计后改文档 | 先跑出结果 → 改一个字 → Save | 顶部红字 **`Report is stale`**：报告绑定旧 `digest`，不能用于审批；点 `Re-audit current snapshot` |
| 停止等待 | 运行中点 `Stop waiting` | 只停止本页等待；没有结论；服务端可能仍在跑。再点 Run/Re-audit |
| 模板不匹配 | template 填 `adidas-guarantee`，对手方不是 Adidas | `Template could not be resolved — reason: no_applicable_template`，计划 57 |
| 未初始化模板 | template 留空 | `No customer template was requested`（不是错误） |
| Gate 未点名 | 不指定操作 | `No operation was asked about, so nothing is allowed` |

> `Gate` 永远一次只回答一个被点名的操作（`start_approval` / `formal_export` / `handoff`）；
> 报告里的 finding 会列出它**阻断哪些操作**。

---

## 9. API 等价操作（可选，方便无 UI 验证）

```bash
B=http://59.110.213.187:8082/api
curl -s -c /tmp/cj -X POST $B/auth/login \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  -d '{"email":"bankops@atlas-trade.test","password":"BankOps!2026"}' >/dev/null

# 1) 把样例文本写成 JSON 请求体（避免 shell 转义）
python3 - <<'PY' > /tmp/run.json
import json
from pathlib import Path
print(json.dumps({"text": Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")}))
PY

TID=$(curl -s -b /tmp/cj -X POST $B/runs \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  --data-binary @/tmp/run.json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["thread_id"])')

# 2) normalize + audit（template 可选）
curl -s -b /tmp/cj -X POST "$B/runs/$TID/stages/normalize?template=adidas-guarantee" >/dev/null
curl -s -b /tmp/cj -X POST "$B/runs/$TID/stages/audit?template=adidas-guarantee" \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);v=d["verification"];a=v["audit"];print("planned",a["planned"],"counts",a["counts"],"coverage",a["coverage"]);print("findings",[(f["rule_id"],f["severity"],f.get("gate_type")) for f in a["findings"]])'
```

> 注意：这里的 `template` 只会**缩小**候选模板，不能指定未发布版本或改版本号。

---

## 10. 预期速查表（线上实测）

| 场景 | 抽取来源 | planned | pass | finding | N/A | needs_input | unable | ratio | outcome |
|---|---|---|---|---|---|---|---|---|---|
| 样例 + template `adidas-guarantee`（对手方 Beta） | deterministic `guarantee-default@1.1.0` | 57 | 36 | 1 | 19 | 0 | 1 | 0.649 | `findings_present` |
| 改 `Issue Date: 01/12/26` + template | deterministic | 57 | 37 | 0 | 19 | 0 | 1 | 0.649 | `unable_to_assess` |
| 改 `Beneficiary: Adidas AG` + template | deterministic（模板命中） | 63 | 38 | 4 | 20 | 1 | 0 | 0.667 | `findings_present` |
| 不填 template | fixture | 56 | 36 | 1 | 19 | 0 | 0 | 0.661 | `findings_present` |

> 这些数字只用于 `Demo_audit.md` 的历史对照；`DEMO.md` 的 8 分钟版**不再以 Rule audit 为主流程**
> （线上已关闭 fixture 抽取，Audit 首屏是"模板一致性审计"）。

---

## 11. 排错

| 现象 | 原因 / 处理 |
|---|---|
| 点 `Run spec audit` 完全没反应 | 旧前端在 **纯 http** 下没有 `crypto.subtle`，快照摘要抛错且请求未发出。硬刷新到新包即可；若仍失败，页面会显示 `SNAPSHOT_FAILED` toast，DevTools → Network 应能看到 `POST /api/runs` |
| `Audit failed — no conclusion produced` / `EMPTY_SUBMISSION` | 正文为空。新建文档默认没有正文：先粘贴/导入（Import file → **Use this text**）并 **Save**；本版在空文本时已禁用 **Run spec audit** 与 **Capture version**，并提示 `Paste or import text into the editor first` |
| 结果区出现 **Fixture-backed run** | 没填 Customer template（ECS 用 fixture 兜底）；填 `adidas-guarantee` 走 deterministic |
| `Template could not be resolved` | 模板要求 `beneficiary_name = Adidas AG`；对手方不匹配或模板未发布（见 `reason` 与 `candidates`） |
| 0 finding 但结论仍是 `unable_to_assess` | 有单元“没查成”（例如模板解析）；0 finding ≠ 合规 |
| 改完文档后报告顶部变红 `Report is stale` | 报告绑定旧快照 digest；点 `Re-audit current snapshot` |
| 一直停在 running | 服务端可能慢；`Stop waiting` 只停本页等待，不给结论。稍后重新 Run/Re-audit |
| bankops 打开已提交文档也能 Run | 审计**不需要编辑锁**；它冻结的是当前草稿文本（审批中草稿=提交快照） |
| 看到 `This submitted version is read-only until it is returned or approved` | 文档已提交（对所有人冻结）。审计仍可跑；要改字就 **Return** 或换一份 `draft`（见 §2.1） |
| 担心审计会改文档 | 不会。审计只创建 `thread` 与报告，不写草稿、不加锁、不提交 |

---

## 12. 一页台词 / 点击路径

```text
① applicant 登录 → Start editing → 粘贴样例 → Save（Saved to server）
② 右侧 Rule audit → Customer template 填 adidas-guarantee → Run spec audit
③ 指指标：Planned 57 / Assessed 37 / N/A 19 / Unable 1 / Hard blocks 1
   指 finding：CO-ISSUE-NOT-PAST（开立日期 2026-03-12 早于今天），阻断 start_approval / formal_export / handoff
   台词：57 项里 36 通过、19 不适用、1 没查成、1 阻断——“没查到”和“通过”分开计数
④ 改 Issue Date: 01/12/26 → Save → Re-audit current snapshot → 0 finding
   台词：但仍有 1 项 unable_to_assess，0 finding 不代表合规
⑤ 改 Beneficiary: Adidas AG → Re-audit → 模板命中：63 planned、4 findings、synthetic: true
   台词：模板会加 3 字段 + 2 条款 + 1 声明；required/controlled/optional 三类的行为不同
⑥ 清空 template → Run → Fixture-backed run（56 planned）
   台词：这条横幅说明候选值来自 fixture，不是这份文档的抽取
⑦（可选）空文档 Run → EMPTY_SUBMISSION；或改一个字再看 Report is stale
```

---

## 附录 A · 样例文本（= `fixtures/llm/sample_document.txt`）

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

## 附录 B · 变体 diff

```diff
# 干净通过（变体 A）
- Issue Date: 12/03/26
+ Issue Date: 01/12/26

# 模板命中（变体 B）
- Beneficiary: Beta Construction Ltd
+ Beneficiary: Adidas AG
```

## 附录 C · 报告落在哪里

- 每次运行生成一个 `thread_id`（如 `R-9c351d02d812`），上传/快照文本在 `runs/<thread_id>/`；
- 报告正文在 assistant 的 SQLite（`SMART_EDIT_ASSISTANT_DB` / 默认 `runs/assistant.db`）；
- **不修改** `documents / document_drafts / document_submissions`，因此演示后无需 reset；
- 想复核同一份报告：`GET /runs/{thread_id}`（需要同一登录会话的权限）。