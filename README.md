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
./scripts/stop.sh                      # 终端已关/进程 nohup 起时收尾（--all 连 e2e 端口一起清）
uvicorn app.api.main:app --reload      # 只要后端时
langgraph dev          # 在 LangSmith Studio 里看图和回放
.venv/bin/python scripts/audit_demo.py   # 规范审计组：一条命令打印计划 / 覆盖率 / 闸门决策（无需模型）
.venv/bin/python -m app.rules.doctor     # 规则包体检：字段引用 / 冲突 / 向量完整性 / 计划单元数（退出码即门禁）
```

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

The knowledge assistant answers from a real legal corpus instead of the synthetic
one. It is opt-in and fails loudly: `SMART_EDIT_STATUTE=on` requires both `MERCATORIA_BASE_URL` and
`MERCATORIA_API_TOKEN`, otherwise startup raises. The order is fixed: **RAG first, model summary
second, web only when RAG returned nothing**. The service's diagnostics (`zero_reason`,
`confidence`, `score`, `degraded`, `requested_uncovered`) annotate the answer instead of discarding
it: hits are always passed to the model together with a "low confidence / jurisdiction not
covered" caveat. Only a zero-chunk or failed response falls back to the general-web channel, which
still sits behind the egress policy and is now on by default
(`SMART_EDIT_ASSISTANT_WEB_DEFAULT=off` turns it off; "both found nothing" is stated explicitly).

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
