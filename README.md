# smart-edit · 智能编辑器 POC

把客户提交的原始材料（邮件、单据 PDF、合同）转成内部系统可识别的标准文件，并在生成过程中完成格式、业务要件、法规三层校验。

**周期**：至 2026-11-18 ｜ **团队**：3 人 ｜ **规格管理**：OpenSpec

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

## 快速开始

```bash
pip install -e .
./scripts/dev.sh                       # 一条命令起后端 :8000 + 前端 :5173；日志实时打印，Ctrl+C 一起停
./scripts/dev.sh --pg                  # PG 身份模式：自动检查/启动 team04 隧道
./scripts/dev.sh --pg --detach --open  # 后台运行 + 自动打开浏览器
./scripts/dev.sh --status              # 查看端口 / PID / PG 隧道 / health
./scripts/stop.sh                      # 停止 dev 服务（后台启动的也能停）
./scripts/stop.sh --tunnel             # 同时关闭 PG 隧道
./scripts/stop.sh --all                # 连 Playwright e2e 端口一起清
uvicorn app.api.main:app --reload      # 只要后端时
langgraph dev          # 在 LangSmith Studio 里看图和回放
.venv/bin/python scripts/audit_demo.py   # 规范审计组：一条命令打印计划 / 覆盖率 / 闸门决策（无需模型）
.venv/bin/python -m app.rules.doctor     # 规则包体检：字段引用 / 冲突 / 向量完整性 / 计划单元数（退出码即门禁）
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
邮箱	密码	角色	部门
admin@atlas-trade.test	AtlasAdmin!2026	Organisation administrator	—
applicant@atlas-trade.test	Applicant!2026	Applicant	Trade Operations
bankops@atlas-trade.test	BankOps!2026	Bank Operations (First Approver)	Bank Operations
compliance@atlas-trade.test	Compliance!2026	Compliance (Second Approver)	Compliance
auditor@atlas-trade.test	Auditor!2026	Auditor	—