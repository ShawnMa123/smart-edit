# smart-edit · 智能编辑器 POC

把客户提交的原始材料（邮件、单据 PDF、合同）转成内部系统可识别的标准文件，并在生成过程中完成格式、业务要件、法规三层校验。

**周期**：至 2026-11-18 ｜ **团队**：3 人 ｜ **规格管理**：OpenSpec

**文档地图**：本文件（架构/契约/API）· **[DEMO.md](DEMO.md)**（评审演示：脚本、样例、运维、Q&A）·
**[how_to_use.md](how_to_use.md)**（逐功能使用说明）· **[deploy/README.md](deploy/README.md)**（部署与排障）

---

## 评审委员会：在线试用（3 步）

| 项 | 值 |
|---|---|
| 地址 | **http://59.110.213.187:8082/** （HTTP，无需 VPN；建议 Chrome/Edge，窗口宽度 ≥ 1400px） |
| 账号 | `applicant@atlas-trade.test` / `Applicant!2026`（提交人）<br>`bankops@atlas-trade.test` / `BankOps!2026`（一审）<br>`compliance@atlas-trade.test` / `Compliance!2026`（二审）<br>`admin@atlas-trade.test` / `AtlasAdmin!2026`（管理员） |
| 健康检查 | `curl http://59.110.213.187:8082/health` → `{"status":"ok","auth_mode":"pg"}` |
| 数据 | 演示组织 `Atlas Trade Bank`（`ws_demo_01`），单一文档 `demo-document` |

### 3 条最值得试的路径

| 想验证什么 | 怎么做 | 预期 |
|---|---|---|
| **合规风险能不能拦住** | 登录 applicant → 编辑器 `Cmd/Ctrl+A` 全选 → 粘贴[制裁样例](fixtures/legal-samples/sanctions-export-zh.txt) → 等 2 秒 → 右侧 `Legal → Document check → Scan document` | `Gate: Blocked`；`Sensitive goods destined for a sanctioned country`（Critical/Blocks），带 `弹药/导弹/军用无人机/伊朗` 四个草稿锚点，点 `Jump to clause` 可回跳 |
| **法条结论有没有证据** | 粘贴[中文保函样例](fixtures/legal-samples/statute-zh.txt) → 同样扫描 | 2 条确定性措辞 + 2 条法条结论（引《…规定》第一条/第三条，附条号/法域/生效日） |
| **要件审计是否逐项可数** | 粘贴[标准保函](fixtures/llm/sample_document.txt) → 右侧 `Audit` → `Customer template` 填 `adidas-guarantee` → `Run spec audit` | 57 项检查：`pass 36 / finding 1 / not_applicable 19 / unable 1`，唯一阻断为"开立日期早于审计日" |

其它可看：`Knowledge` 点「独立保函必须载明哪些事项才有效？」（约 10 秒，5 条引用）；
用 `bankops` / `compliance` 登录后在 `Approval` 完成一审/二审；顶栏 `Activity` / `People` / `Developer`。

### 试用时请留意（也是我们想被检验的点）

- **粘贴会替换当前草稿**（演示只有一份文档）。想恢复初始文本：
  `ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py'`
- **"没查到"不等于"没问题"**：报告里 `Planned N · assessed M (x%)`、`unchecked_units`、`low_confidence`
  就是在区分"检查过并放过"与"根本没查成"。
- **模型不能造证据**：法条结论只能引用检索到的 chunk；模型不能把严重度提到 `Critical`，也不能直接阻断。
- **联网是用户选择**：默认关闭；勾选后只把未覆盖条款的标题发出去，结果一律标 `Unverified web source`。
- **英文条款常显示 "Unable to assess"**：法规语料目前以 CN/EU/INT/US/WTO 的贸易与海关规则为主；
  这是如实告知，不是故障（换成中文样例即可看到法条结论）。
- **不是筛查服务**：没有接 OFAC/BIS 名单，也没有货物分类与许可判断；结论是"需要人复核的红黄线"。

完整脚本、样例全文、故障排查与 Q&A 预演见 **[DEMO.md](DEMO.md)**。
遇到问题先看 `deploy/README.md` 的排障表，或把 `http://59.110.213.187:8082/health` 的返回贴给我们。

> 想在自己机器上跑：见下文 **[本地运行（5 分钟）](#本地运行5-分钟)**（不需要模型 key 也能跑主要功能）。

---

## 规格（OpenSpec）

所有设计与规格集中在 `openspec/`，不再另设设计文档。契约的唯一真相源是
`openspec/changes/poc-skeleton/design.md`。

```bash
openspec list          # 查看进行中的 change
openspec status --change <name>
openspec validate --all
```

三人四职。每个 change 目录名即 owner 的责任范围，**不要从名字猜，按下表对照**：

| Change 目录 | Agent | 中文名 | Owner | 内容 |
|---|---|---|---|---|
| `poc-skeleton` | — | 地基 | **待定** | 契约冻结 + 共享层（parse/extract/normalize）+ 主图 + 阶段状态 + 操作留痕 + 独立触发 |
| `agent-normalize` | **Agent 1** | 标准化 | **A** | 原始材料 → 结构化字段 + 出处 |
| `agent-verify` | **Agent 2** | 要件校验 | **B** | 逐字段值校验 + 齐全性 + 业务参数 |
| `agent-regulatory` | **Agent 3** | 法规合规 | **C** | RAG 检索 + 两种输入模式 + 覆盖声明 |
| `agent-audit` | **Agent 4** | 审计 | **C**（框架）/ **A**（`provenance_check`） | 证据链校验 + 可信度 + 受控重跑 |

> ⚠️ **`agent-verify` 是 Agent 2（B），`agent-audit` 是 Agent 4（C）。**
> 早期版本中 Agent 4 叫 `agent-verifier`，与 `agent-verify` 易混，已改名。
> 也不用 `benchmark` —— 在线校验（运行路径上查证据链）与离线 benchmark（开发机上有真值判对错）
> 是两回事，混用会导致"用评测口径做运行时阻断"这类错误。

**执行顺序**：`poc-skeleton` 的**契约（tasks 2.x）与共享层（tasks 3.x）必须先完成并冻结**，
之后四个 Agent 的 change 才能真正并行 —— 因为独立触发要求所有 Agent 共用同一份解析实现。

---

## 架构一句话

```text
ingest → parse → extract → normalize → reset → (Agent2 要件校验 ‖ Agent3 法规合规) → merge
       → Agent4 Verifier → ⏸ 人工核对 → 闸门 → 导出
```

四人分工：① 只改形式不改事实 ｜ ② 值合不合法、材料全不全 ｜ ③ 有没有不符规则之处 ｜ ④ 证据链可不可信。

> 说明：四类能力由三人分担 —— 前三类各一人，第四类与 Agent 3 同一人。

**独立触发**：`agent1/2/3` 可被前端单独调用，系统自动补齐其声明的前置阶段；`agent4` 通过注册的
`audit` 阶段目标触发（`POST /runs/{tid}/stages/audit` 或 `.../stages/agent4`，两者同一实现），
前置为 `parse → extract → normalize`。

---

## 硬约束（不可违反）

1. **Agent 1 只改形式不改事实**，能跳回原文的字段才标 `extracted`
2. **Agent 1 / 2 用 YAML 配置，不用 RAG**（确定性要求）
3. **Agent 4 只做可判定检查**，不评业务对错；可信度用可复算比率，不用主观分数
4. **闸门不确定时默认 blocked**
5. **检索为空时输出"未覆盖"，永不输出"无问题"**
6. **"没发现问题"与"没检查"必须在数据结构上可区分**（`StageReport`）
7. **对原文的每次自由操作都要留痕**，概括/改写/丢弃即为越界（`TrailEntry`）
8. **前置缺失时拒绝执行，不返回空结果**

---

## 本地运行（5 分钟）

### 0. 前提

- Python ≥ 3.11（3.12 验证过）、`pip`
- Node ≥ 18 + `npm`（前端 Vite 5）
- macOS / Linux（Windows 建议 WSL）
- 不需要模型 key、不需要数据库也能把主要功能跑起来（见 §本地能力对照）

### 1. 装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .     # 后端：FastAPI / LangGraph / PyMuPDF / psycopg …
npm --prefix web ci                      # 前端（或 npm --prefix web install）
cp .env.example .env                     # 可选；不配也能跑，见下一节
```

### 2. 起服务

```bash
./scripts/dev.sh          # 后端 :8000 + 前端 :5173，日志同屏；Ctrl+C 一起停
```

浏览器打开 **http://localhost:5173**（Vite 默认只监听 `localhost`，用 `127.0.0.1` 可能打不开；
它把 `/api` 代理到 `127.0.0.1:8000`，与线上 nginx 行为一致）。

### 3. 本地能力对照（不配 `.env` 时）

| 能力 | 本地默认 | 说明 |
|---|---|---|
| 规则审计 `Audit`（要件/规则/覆盖率/闸门） | ✅ 完整 | 确定性抽取 profile + 规则包，不需要模型 |
| 法规/合规扫描的确定性部分 | ✅ 完整 | 要素、日期、高风险措辞、制裁/出口管制组合判定 |
| 法条证据（RAGFlow） | ⚠️ 关闭 | 需要 `SMART_EDIT_STATUTE=1` + `MERCATORIA_BASE_URL/TOKEN` |
| 模型综合 / 联网 | ⚠️ 关闭 | 需要 `SMART_EDIT_ASSISTANT_*`（Ark key）；关闭时结论显示 `unable_to_assess`，不会假装通过 |
| 账号登录 | fake 模式 | 没有登录页，直接进入演示工作台；真实账号见 §5 |

### 4. 想开完整能力

复制 `.env.example` 为 `.env`，填 Ark key 与 Mercatoria 地址（都在 `.env.example` 的注释里）；
或者直接用线上站（见上一节"评审委员会：在线试用"），那里模型、法规语料、真实账号都是开着的。

### 5. 真实账号模式（仅内部，需要 team04 PG 隧道）

```bash
ssh -f -N team04-pg                                # 127.0.0.1:15432 → RDS
./scripts/dev.sh --pg                              # 自动检查/启动隧道
.venv/bin/python scripts/seed_identity_users.py    # 写 5 个演示账号（密码见 DEMO.md）
```

### 6. 测试与自检

```bash
.venv/bin/python -m pytest tests -q                            # 后端：856 passed / 27 skipped
npm --prefix web run typecheck && npm --prefix web run test    # 前端：typecheck + 545 passed
.venv/bin/python -m app.rules.doctor                           # 规则包体检（退出码即门禁）
.venv/bin/python scripts/audit_demo.py                         # 打印计划/覆盖率/闸门（无需模型）
```

### 7. 常见问题

| 现象 | 处理 |
|---|---|
| `缺少 .venv` / `缺少 web/node_modules` | 按 §1 安装（`dev.sh` 会打印确切命令） |
| 端口被占用 | `./scripts/dev.sh --status`；或加 `--force`；或 `PORT=8010 WEB_PORT=5174 ./scripts/dev.sh` |
| 页面能开但接口 404/500 | 后端没起：`./scripts/dev.sh --status`，或单独 `uvicorn app.api.main:app --reload` |
| 打开 5173 没看到登录页 | 本地是 `fake` 身份模式，这是预期；要登录页用 `--pg` |
| `127.0.0.1:5173` 打不开、`localhost:5173` 正常 | Vite 默认只监听 `localhost`（IPv6）；用 `localhost` 即可 |
| `--pg` 报 PG 不可达 | 先 `ssh -f -N team04-pg`，或改用 `--fake` |
| Playwright e2e 缺浏览器 | `cd web && npx playwright install chromium` |
| 改了后端不生效 | `dev.sh` 默认**不**热重载：Ctrl+C 后重跑；需要自动重载就直接 `uvicorn app.api.main:app --reload` |

### 8. 开发命令速查

```bash
./scripts/dev.sh                       # 后端 :8000 + 前端 :5173
./scripts/dev.sh --pg --detach --open  # PG 身份 + 后台 + 自动开浏览器
./scripts/dev.sh --honest              # 关掉模型 provider（演示"检查没跑"的诚实路径）
./scripts/dev.sh --status              # 端口 / PID / PG 隧道 / health
./scripts/stop.sh                      # 停止 dev 服务
./scripts/stop.sh --tunnel             # 同时关 PG 隧道
./scripts/stop.sh --all                # 连 Playwright e2e 端口一起清
uvicorn app.api.main:app --reload      # 只要后端
langgraph dev                          # LangSmith Studio 里看图和回放
```

---

## 账号、组织与授权（`user-management`）

默认 `SMART_EDIT_AUTH_MODE=fake`：仅本地演示使用 `X-Demo-User`，不会连接 PG。真实账号模式：

```bash
# 1) 依赖：psycopg[binary] / psycopg_pool / argon2-cffi（pyproject 已声明）
uv pip install -e .            # 或 .venv/bin/python -m pip install -e .

# 2) PG 隧道 + 连接串（沿用 SMART_EDIT_DATABASE_URL）
ssh -f -N team04-pg            # 127.0.0.1:15432 -> team04
SMART_EDIT_AUTH_MODE=pg \
SMART_EDIT_DATABASE_URL='postgresql://...@127.0.0.1:15432/team04' \
uvicorn app.api.main:app --reload
```

- **启动即校验**：`AUTH_MODE=pg` 时连接池 + `SELECT 1` + 编号 SQL 迁移（`app/identity/migrations/`，`schema_meta.schema_version`）在启动阶段完成；PG 不可达会直接报错并提示 `SMART_EDIT_DATABASE_URL` / `team04-pg`，**不会**回退到 SQLite 或假身份。
- **账号**：邮箱唯一、`argon2id` 哈希（`SMART_EDIT_ARGON2_*` 可调）、登录失败按 IP+邮箱限流（`SMART_EDIT_AUTH_LOGIN_*`）。会话是服务端不透明令牌，cookie 为 `HttpOnly; SameSite=Lax`，生产设 `SMART_EDIT_AUTH_COOKIE_SECURE=1`。
- **角色与继承**：`org_admin` / `dept_admin` / `member` / `auditor` / `applicant` / `bank_ops` / `compliance`；角色挂在组织或部门上，生效权限 = 组织级 + 资源部门祖先链上的并集，**没有 deny**；收权即删除 assignment。最后一名有效 `org_admin` 不能被移除/停用。
  - 测试账号（Applicant / Bank Operations First Approver / Compliance Second Approver）：`.venv/bin/python scripts/seed_identity_users.py --reset`，账号与密码打印在终端并写入 `runs/dev/test-users.md`。
- **资源范围（Option B）**：文档 `department_id=NULL` = 组织级（所有 active member 可读）；部门级文档只对祖先链上拥有 `document.read` 的人员可读；写/锁/导出分别要求 `document.edit/lock/export`。所有业务 API 以服务端存储的 scope 判定，客户端提交的 `workspace_id/department_id` 不作为授权依据。
- **邀请 v1**：生成一次性 token（只存哈希，默认 72h），管理员复制链接线下发送；**不发邮件、不做邮箱验证/自助找回密码**；接受一次后失效，邀请人不能授予超出自身权限的角色。
- **Developer**：API Key 高熵、只存哈希、只在创建时显示一次；`Authorization: Bearer <key>` 映射为服务主体，scopes 与创建者**当前**权限取交集（失权即失效）；请求日志只记 method/path/status/latency/key，不含 body/令牌。`developer.manage` 保护页面与接口；**Webhook 首版不提供**。
- **Activity**：登录/登出、组织/部门、成员/角色、文档提交/锁、助手 run、API Key 变更均由服务端写事件；组织级事件对所有成员可见，部门级事件按 `activity.read` 的祖先链过滤；已读状态按用户独立保存。
- **提交与两级审批**：`POST /documents/{id}/submissions` 冻结不可变版本；`GET /approvals?stage=first|second`、`GET /approvals/{id}`、`POST /approvals/{id}/decisions` 支持 `approve / return / reject`。审批中与已批准版本只读，退回后可修改并重新提交；禁止审批自己提交的请求；本轮不发送邮件、不接 AI audit gate。
- **审批界面**：文档头、My submissions 与顶部 badge 共用一套状态（Draft / Pending first / Pending second / Approved / Returned / Rejected）；待审批时显示 Waiting banner + 四步进度、当前角色、提交时间、revision 与最近意见；顶部 Approval 使用 `/approvals` 聚合的待办数（0 隐藏、>99 为 `99+`），Activity 使用 `/activity/unread-count`；提交、决策、复制邀请走语义 Toast；申请人在 pending 时每 10s 刷新，页面隐藏暂停、终态停止。

---

## HTTP API (console transport)

Contract: `openspec/changes/frontend-console/specs/console-api/spec.md`.

```bash
# 1. dependencies (the repo venv has no pip of its own)
~/.local/bin/uv pip install --python .venv/bin/python -e '.[dev]'

# 2. model provider for extraction — unset means `extract` fails loudly, by design
export SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json

# 3. server
.venv/bin/uvicorn app.api.main:app --reload
```

| Endpoint | Purpose |
|---|---|
| `POST /runs` | Create one run. Multipart with field `files`, or JSON `{"text": "..."}` for pasted text |
| `POST /runs/{thread_id}/stages/{stage}` | Run a stage chain (`parse` / `extract` / `normalize` / `audit`), backfilling prerequisites |
| `GET /runs/{thread_id}` | Read the envelope: `fields`, `extra_fields`, `findings`, `stages`, `trail`, `verification`, `gate`, `supported_stages` |

`verification` / `gate` are `null` until they mean something: `null` verification = no audit yet, `null`
gate = nobody asked the gate. Neither is ever "clean". The audit decides no operation by itself — a
decision appears only when one is asked for (`gate.evaluate(state, operation, digest)`).

```bash
# create a run from the bundled sample document, then audit it
TID=$(curl -s -X POST localhost:8000/runs \
        -F "files=@fixtures/llm/sample_document.txt;type=text/plain" \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["thread_id"])')

curl -s -X POST "localhost:8000/runs/$TID/stages/normalize" | python3 -m json.tool | head -40
curl -s -X POST "localhost:8000/runs/$TID/stages/audit" | python3 -m json.tool | head -40
curl -s "localhost:8000/runs/$TID" | python3 -m json.tool | head -20
```

`SMART_EDIT_LLM` values: unset → `extract` records `failed` (no invented candidates);
`fixture:<path>` → replays that file and says so in the stage `reason`; `openai:<model>` → reserved,
raises `NotImplementedError`.

#### Deterministic extraction (config-driven-audit-extraction)

`fixture:` is a **demo / regression path only** — it replays the same candidates for every document.
For real text, name a published extraction profile; the `extract` stage then reads the current
`docs.blocks`, needs no model (`model_calls=0`) and is reproducible:

```bash
# the shipped profile: app/configs/extraction/guarantee-default.json
curl -s -X POST \
  "localhost:8000/runs/$TID/stages/audit?profile=guarantee-default&as_of=2026-03-12" \
  | python3 -m json.tool | head -40

# the customer template names the same profile; an explicit ?profile= wins over it
curl -s -X POST \
  "localhost:8000/runs/$TID/stages/audit?template=adidas-guarantee&as_of=2026-03-12" \
  | python3 -m json.tool | head -40
```

- Profile = **where** a value is found (labels/aliases, `value_kind`, `same_block` /
  `same_or_next_block`, confidence). It only references `fields.yaml` keys; unknown keys, unknown
  `value_kind`, regexes or scripts are load errors.
- An unknown / unpublished / type-mismatched profile is refused (`400 invalid_extraction_profile`) —
  never silently replaced by the fixture.
- `verification.extraction` names the source (`deterministic` / `fixture` / `llm` / `unknown`),
  profile id/version/hash and `fields_found` / `fields_missing`; `verification.policy` names the
  template id, bundle versions and `as_of`. The UI shows the same block above the gate.
- `?as_of=YYYY-MM-DD` fixes the audit date used by `relative_date: today`; it defaults to the server's
  today and is always echoed in `verification.audit.as_of`, so the same date + text replays exactly.
- Company policy is a normal rule bundle: `app/rules/bundles/company-guarantee.yaml` (issue date not
  before `today`, desk amount limit, URDG 758 / payment wording, allowed currencies). Every rule has
  test vectors; `.venv/bin/python -m app.rules.doctor` must stay green before publishing.

To add a field: declare it in `app/configs/fields.yaml`, add its locator to the profile JSON, and (if
it needs a business rule) add a rule + vectors to a bundle. To add a policy: copy the company bundle,
bump `version`, publish it, and run the doctor. `openspec/changes/config-driven-audit-extraction/`
describes the contract in full.

### Statute evidence (knowledge-statute-retrieval, off by default)

The knowledge assistant answers rule questions through Mercatoria's `/v1/chat` endpoint
(retrieval + a server-side draft with chunk citations), then asks Doubao to structure/polish that
draft; the final answer still goes through the local reviewer and the source marker. It is opt-in
and fails loudly: `SMART_EDIT_STATUTE=on` requires both `MERCATORIA_BASE_URL` and
`MERCATORIA_API_TOKEN`, otherwise startup raises. `/v1/retrieve` remains in the codebase for offline
replay and rollback, but the pipeline no longer calls it. Product FAQs stay on the local corpus
(chat would answer them from legal texts). `MERCATORIA_CHAT_TIMEOUT` (default 60s) bounds the chat
call; the web fallback still runs only when chat returns no usable answer, behind the egress policy.
References returned by chat are evidence even when chat's own `answer_status` is
`unavailable`/`unsupported`; only a zero-reference response falls back to the web.
Note that chat's generation happens on the Mercatoria side, outside this service's egress audit.

```bash
export SMART_EDIT_STATUTE=on
export MERCATORIA_BASE_URL=http://127.0.0.1:18080      # or the intranet endpoint
export MERCATORIA_API_TOKEN=<token>
.venv/bin/python scripts/statute_eval.py                # offline decision-layer report (15 cases)
```

### Document risk scan (`legal-document-risk-scan`)

`Legal → Document check` in the assistant pane scans **the draft on screen**, not a free-form question:

```text
draft → clauses (with code-point anchors) → plan (= coverage denominator)
      → deterministic checks (elements / dates / risky wording)
      → one /v1/retrieve per clause (never /v1/chat for a scan)
      → Doubao composes only from the given evidence ids
      → optional web supplement (user switch, unverified, never hard-blocks)
      → findings + coverage_summary + gate
```

Things that will not happen, by construction:

- A clause that was never planned can never read as "checked". `assessed/planned < 0.6` adds
  `limited_coverage`; any `failed`/`unable_to_assess`/`needs_input` unit adds `unchecked_units`.
- The model cannot invent evidence (`evidence_ids` are filtered), cannot raise `severity` above
  `Warning`, and cannot `hard_block`. Only deterministic rules (missing amount/expiry, inverted
  dates, expired undertaking) do that.
- A `quote` in `document_anchors` is always a real substring of the draft; the panel's
  "Jump to clause" focuses the editor at that block.
- The web leg is off unless the operator ticks it (`web_search`); results are `unverified` and
  carry a link, and an unlinkable result is dropped.

`scope=document` runs in the background (202 + `GET /legal/runs/{id}`); reports persist in
`SMART_EDIT_LEGAL_DB` (default `runs/legal.db`), and a scan pinned to a revision that changed is
refused with `stale_snapshot`. Spec: `openspec/changes/legal-document-risk-scan/`.

A run may also carry an **explicit scope** (`jurisdiction_codes`, `applicable_on`, `rule_version`).
Declaring any of them marks the question as a rule question: it is routed to statute retrieval first
and only falls back to the web when that evidence is unusable. Unscoped runs behave exactly as before,
and a rule version never narrows retrieval by itself — it only settles applicability.

**Term normalisation.** Generic words are rewritten into the corpus's controlled terms before
retrieval (`knowledge.sample.json` → `query_expansion`), so `guarantee` also searches
独立保函 / 见索即付保函 / demand guarantee. The original wording is always kept; the table is capped
(≤4 terms per word, ≤12 total) and the terms actually used are written to the run audit.

**"Searched but rejected" is stated.** When the statute leg ran and was not usable — low confidence,
zero hits, uncovered jurisdiction, service down — the answer says so with the hit count, even when the
internal corpus answered. The transparency is deliberate: the reader must be able to tell "we did not
look" from "we looked and rejected it".

### Server-side automation registry (`automation-template-registry`)

The Automation tab has two areas:

| Area | What it is |
|---|---|
| **Automate** (default) | The real path: server templates, Doubao variable suggestions, contract-shaped body, a review card, `Preview request`, and dispatch with a receipt. |
| **Sandbox** | A browser-local playground (`localStorage`, no external calls except the two stateless helpers below): local templates, variable marking/filling, and a payload preview. It cannot send — that is what `Automate` is for. |

The sandbox preview does **not** re-implement the contract rules: it calls `POST /automation/spec/parse`
(operations + fields) and `POST /automation/spec/build` (request body), so the browser and dispatch share
one OpenAPI subset and one body builder.

| Endpoint | What it does |
|---|---|
| `POST /automation/templates` | Save the current draft / imported text as a server template (same name → patch version) |
| `PUT /automation/templates/{id}` | Rename one stored version (a `(name, version)` clash is refused) |
| `POST /automation/templates/{id}/duplicate` | Copy text + confirmed variables under a new name |
| `DELETE /automation/templates/{id}` | Remove one version; dispatch receipts keep their own snapshot |
| `POST /automation/templates/{id}/apply` | Render the template into a **new document** (`{{label}}` / `[[label]]` / `Label:` lines) |
| `POST /automation/templates/{id}/write-back` | Write the values into the **current draft** under the editor's lock + expected revision |
| `GET /automation/templates` · `GET /automation/templates/{id}` | List / read (workspace-scoped) |
| `POST /automation/templates/{id}/variables/suggest?use_llm=false` | Deterministic candidates + optional Doubao; never persists |
| `PUT /automation/templates/{id}/variables` | Persist the **confirmed** set (the only write a suggestion can lead to) |
| `POST /automation/templates/{id}/prepare` | Bind `label: value` from a draft; missing required values are reported |
| `POST /automation/connectors` · `GET /automation/connectors` | Register a downstream (secret is an env var **name**); may carry an OpenAPI 3.x JSON spec + operation |
| `PUT /automation/connectors/{id}` | Edit a target in place; replacing the spec (or its operation) resets the field mapping |
| `GET /automation/connectors/{id}/spec` | Read the stored OpenAPI document for the editor (list responses stay small) |
| `DELETE /automation/connectors/{id}` | Soft delete: receipts stay for audit, dispatch refuses the target |
| `PUT /automation/connectors/{id}/mapping` | Bind the operation's request-body fields (dotted paths) to template variables; `template_id` stores it **per (template, connector)** |
| `GET /automation/mappings?template_id=&connector_id=` | Read that pair mapping (`configured=false` → the panel suggests by label) |
| `POST /automation/spec/parse` | Parse an OpenAPI document with the registry's own rules (stateless; used by the sandbox) |
| `POST /automation/spec/build` | Assemble a request body from a spec + mapping (stateless preview; nothing persisted) |
| `POST /automation/dispatches/preview` | Resolve URL / masked headers / body for a dispatch — no HTTP call, no receipt |
| `POST /automation/dispatches` · `GET /automation/dispatches` | One real HTTP call + receipt (status/latency/response excerpt) |

Rules that hold by construction:

- A suggestion is not a save: `suggest` is read-only, and every suggested variable carries a
  `quote` that must be locatable in the template (otherwise `quote=None` + `quote_not_found:<label>`).
- Deterministic first, model second: placeholders (`{{x}}`), blanks (`____`) and `Label: value` lines
  work without a model; if Doubao is unavailable the endpoint degrades with `llm_unavailable`, never 500.
- One field per fact: a model variable that renames what the regex already read (`applicant_name` vs
  `applicant`, or a second label on the same `Amount:` line) is folded into that field, so the panel
  never asks you to confirm the same value twice.
- Binding never guesses: `prepare` only matches labels (`applicant_name` ↔ `Applicant:`) and reports
  `missing_required` instead of inventing a value.
- Dispatch is allow-listed: hosts must be in `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS` (empty = deny all),
  https only unless `SMART_EDIT_AUTOMATION_ALLOW_HTTP=1`. Secrets come from the env var named in
  `secret_env` — never stored, never echoed. Refusals are recorded with `status=refused`
  (`host_not_allowed` 403 / `tls_required` 403 / `secret_missing` 409).
- Connectors list oldest-first, so registering another system never silently re-points the panel's
  default send target.
- Mappings belong to a **(template, connector) pair**: one ERP endpoint can serve a guarantee template
  and an invoice template with different field names, and saving one never overwrites the other.
  A connector-wide mapping from before pair mappings (no `template_id`) is still honoured as a fallback.
- The panel is guided: a `Step n/m` card names the one control to use next (`Show me` scrolls to it),
  shows the checklist and the chosen `Target`, pre-fills the spec mapping from the confirmed variables,
  and explains why `Send` is disabled (`Send is blocked: beneficiary.name still needs a value`).
- Four sections, one card for the risky part: `1 Template` → `2 Fields` → `3 Downstream` (choose or add
  a connector, with its `Field mapping` behind a disclosure) → `4 Review & send`, which is a **read-only
  review** (mapping + values + request body) plus exactly two actions: `Preview request` and `Send`.
  The values are filled from the draft automatically, so "check → preview → send" never straddles the
  connector picker and never needs a "fill" click.
- Targets are editable and retireable: `Edit connector` changes name/host/path/auth **in place**
  (`Load saved spec` re-opens the stored document), and `Disable connector` soft-deletes it — the
  receipts stay for audit while dispatch refuses the target.
- Templates have a lifecycle too: `Rename` / `Duplicate` / `Delete` act on the selected version.
  Rendering a template into a **new draft** (`POST /automation/templates/{id}/apply`) and writing the
  reviewed values into the **current** draft (`POST …/write-back`, lock + `expected_revision`, a stale
  revision answers `412 stale_draft`) stay available over the API, but the panel itself is review-only.
- Two conveniences: `Step-by-step` shows one section at a time (Back/Next, guide stays authoritative),
  and the template name defaults to the draft's first line with a "saving adds a new version" hint.
- `Preview request` replaces the old mock send: it returns the exact URL, header names (values masked as
  `***`), body and body issues with **no** HTTP call and **no** receipt, so a demo works without a partner.
- The receipt is informational: status, status code, latency, dispatch id and the response excerpt.
  Each receipt still records `target` (url/method/schema kind) and `sent_body` for audit, and the
  collapsed history list filters by `succeeded / failed / refused`.
- The request body follows the downstream's own contract: attach its OpenAPI 3.x JSON and pick an
  operation, **or** write the fields by hand (`amount: number *`) when the partner publishes no spec —
  both paths share one mapper, validator and body builder (`schema_kind` is `openapi` / `fields` / `flat`). `prepare`/`dispatch` then build `{...}` with dotted paths (`beneficiary.name`), convert
  numbers (a currency-prefixed `USD 750,000.00` becomes `750000.0`), omit unmapped optional fields and
  refuse `missing_required_body` (409) instead of sending a body the spec forbids. `oneOf`/`anyOf`,
  arrays, external refs and cycles are reported as unsupported, never guessed. Without a spec the
  legacy flat `{template, values}` payload is still sent, so older connectors keep working.
- Idempotent: the same `idempotency_key` returns the original receipt without a second call.
- Permissions: reads need `read`, writes and dispatch need `apply`.

Importing a downstream contract: `Automation → Automate → 3 · Downstream → Add connector`
takes an OpenAPI 3.x **JSON** document either pasted or chosen with **Import OpenAPI spec file**
(`/openapi.json`, Spring's `/v3/api-docs`, Swagger Editor "Download JSON", an API-gateway export).
Swagger 2.0 / YAML are rejected with an explicit message. The same thing over the API:

```bash
curl -X POST http://localhost:8000/automation/connectors \
  -H 'Content-Type: application/json' -H 'X-Requested-With: smart-edit' \
  -b cookies.txt \
  -d '{"name":"Trade intake","base_url":"http://127.0.0.1:18080",
       "spec":'"$(cat fixtures/automation/openapi_sample.json)"',
       "operation":"POST /trade/applications"}'
```

Try it locally without a downstream system:

```bash
.venv/bin/python scripts/echo_downstream.py --port 18080     # POST /hooks/smart-edit echoes JSON
export SMART_EDIT_AUTOMATION_ALLOWED_HOSTS=127.0.0.1
export SMART_EDIT_AUTOMATION_ALLOW_HTTP=1
# then: Automation → Automate → save template → Find variables with AI → confirm
#       → connector http://127.0.0.1:18080 → review the body → Send
```

### Web fallback and knowledge presets (`knowledge-simple-ask`)

| Variable | Default | Effect |
|---|---|---|
| `SMART_EDIT_ASSISTANT_WEB_DEFAULT` | `on` | Whether the web fallback starts enabled. Deployment policy, not a UI decision. |
| `SMART_EDIT_KNOWLEDGE_CONFIG` | unset | Path to a knowledge config JSON; overrides the shipped sample. |
| `SMART_EDIT_ASSISTANT_EGRESS_POLICY` | unset | Legacy name for the same path (kept for compatibility). |

`app/configs/knowledge.sample.json` holds the outbound preset: allowed domains, query length, the
redaction rules, the jurisdiction presets and the suggested questions. Copy it and point
`SMART_EDIT_KNOWLEDGE_CONFIG` at the copy to change any of them without touching code. A missing or
broken file denies every outbound call; a rule that does not compile fails at start-up; at most 32
rules of at most 512 characters each; and the "public rule ids must survive redaction" exemption
(URDG/UCP/ISP…) is fixed in code so a config cannot whitelist an amount.

Each run records the effective `web_search` value and `web_search_source` (`user` / `default`) in its
audit payload, so "did this question leave the building, and who decided" is provable after the fact.

Two web channels keep different trust rules: `approved_web` only cites allow-listed domains, while
`general_web` (the model's own web search) cites any result that carries a resolvable `http(s)` link
and is always labelled unverified. Results without a usable link are never cited, and the audit
records their host names so the policy can be reviewed.

Errors always come back as `{code, message, detail?}` with `code` one of `EMPTY_SUBMISSION` (400),
`unknown_run` (404), `unknown_stage` (409), `REFUSED` (409), `NOT_STANDALONE` (403),
`INCOMPLETE_RESULT` (500). Branch on `code`, not on `message`.

Run state is process-scoped: after a restart the same `thread_id` answers `unknown_run` — never an
empty run. Re-auditing means creating a new run, because `normalize` clears `_candidates` and a
repeat trigger is refused.


-----------
邮箱	                      密码	            角色	                              部门
admin@atlas-trade.test	    AtlasAdmin!2026	  Organisation                      administrator	—
applicant@atlas-trade.test	Applicant!2026	  Applicant	Trade                   Operations
bankops@atlas-trade.test	  BankOps!2026	    Bank Operations (First Approver)	Bank Operations
compliance@atlas-trade.test	Compliance!2026	  Compliance (Second Approver)	    Compliance
auditor@atlas-trade.test	  Auditor!2026	                                      Auditor	—
-----------