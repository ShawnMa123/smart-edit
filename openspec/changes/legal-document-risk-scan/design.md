# Design

## Context

- 现有 `legal-review`（L1）：`POST /legal/reviews` 同步、内存、只有 `question` 一种输入；`legal` mode 走
  `/v1/chat`（检索 + 服务端 LLM），无法逐条款复核。
- 已有可复用件：`app/documents/projection.py`（code-point 偏移）、`app/rules`（三值逻辑）、
  `app/assistant/statute.py`（`/v1/retrieve`、`/v1/chat`、`score/coverage/diagnostics` 映射）、
  `app/assistant/gateway.py`（Responses API）、`app/assistant/egress.py`（脱敏/白名单）、
  `app/audit/{planner,gate}.py`（计划 = 覆盖率分母、按操作分闸门的口径）。

## Decisions

### D1 · 先计划、再评估；锚点必须是原文子串

`split_clauses()` 把 `project_document()` 的顶层 block 聚成 clause，保留 `start_cp/end_cp/block_index`；
标题行、编号条目或超过 `CLAUSE_CHARS` 才切分。`planned = 元素 + 一致性 + 每条款 presence(+statute) + 可选 web`。
超过 `MAX_CLAUSES` 时截断并在 `coverage_summary.truncated` + `limitations` 如实说明。
- 备选：按段落长度机械切分 —— 否决：会把「第 7 条 + 其子款」切开，锚点也会落在句子中间。
- 代价：没有编号/标题的长文本会成为少数几个大 clause；由 `CLAUSE_CHARS` 兜底。

### D2 · 逐条款用 `/v1/retrieve`，不用 `/v1/chat`

`/v1/chat` 自带服务端 LLM（默认 60s 预算），逐条款调用慢、贵，且把「服务端模型的答案」当证据，无法复核。
扫描链路改为每条款一次 `/v1/retrieve`（`top_k=5`、`filters={jurisdictions, as_of}`），
用服务自己的 `diagnostics.zero_reason` / `field_matches.requested_uncovered` / `low_confidence` 判定可用性：
- 零命中 → `unable_to_assess`（`zero:*`），并进入「未覆盖」集合；
- `uncovered:*` / `low_confidence` / `superseded` → 有命中但**不构成结论**，记 `unable_to_assess` + 证据计数；
- 仅「有命中且服务未告警」才交给 composer。
`question` scope 仍保留 `/v1/chat`（advice 标签页不变）。

### D3 · 证据约束的综合：composer 不能提升 severity 或 gate

`LegalComposer.review_clause()` 只把 `rules`（本条款命中的确定性规则 + `LEGAL-RISK-NEW`）与 `evidence`
（`id/article_label/jurisdiction/effective_from/excerpt`）交给模型，输出 JSON 后逐条校验：
- `rule_id` 必须在给定 catalogue 内（否则丢弃）；
- `evidence_ids` 必须 ⊆ 给定 id（未知 id 丢弃）；无引用时 `support_level` 强制 `insufficient`；
- `severity` 最多 `Warning`、`gate_type` 最多 `human_review`（`Critical`/`hard_block` 只来自确定性规则）；
- `quote` 必须在 clause 原文中定位得到（空白容错匹配），定位失败则不产生草稿锚点。
模型不可用（fixture、未批准、无 key）→ 每个条款 `unable_to_assess` + `composer_unavailable`，**不造假 pass**。

### D4 · 联网是用户选择，且永不阻断

`web_search: bool | null`；`null` 用部署默认 `SMART_EDIT_LEGAL_WEB_DEFAULT=off`。只在「有条款未被语料覆盖」时触发一次，
问题只带 clause 标题（不带正文），结果 `basis=web`、`support_level=insufficient`、`gate_type=human_review`、
`unverified=true`，`url` 必须可解析（`http(s)`）否则丢弃。报告写 `retrieval.web_requested/web_used/web_calls`。
- 备选：默认联网 —— 否决：文档正文比一个问题敏感得多，默认外发不可接受。

### D5 · 闸门 = findings + 覆盖率 + 未检查单元

`gate_for()`：任一 `hard_block` finding → `blocked`；`assessed_ratio < COVERAGE_RATIO(0.6)` → `limited_coverage`；
存在 `failed/unable_to_assess/needs_input` 单元 → `unchecked_units`；有 `human_review` finding → `human_review_finding`。
`blocked` 优先，其余任一原因 → `needs_human_review`，仅 advisory finding → `advisory`，否则 `clear`。
理由随报告返回，前端逐条展示；**任何「没查到」都不会折叠成 `clear`**。

### D6 · 异步 run + 轮询 + 落盘 + 幂等

`scope=document` 立即 202（`queued`），`BackgroundTasks` 执行；`GET /legal/runs/{id}` 返回
`stage/progress{stage,planned,done,current,findings}`。报告与 run 落 SQLite（`SMART_EDIT_LEGAL_DB`，默认 `runs/legal.db`），
`Idempotency-Key` 复用同一 run；`expected_revision`/`expected_content_sha256`/`draft_id` 与当前草稿不符 → run `failed` + `stale_snapshot`。
- 备选：同步 200 —— 否决：8–20s 的请求会撞上网关/浏览器超时，也没有进度可看。
- 代价：进程内 SQLite；L2 若要多实例再迁 PG（`legal_runs/legal_reports/legal_idempotency` 三张表已按此形状设计）。

### D7 · 确定性规则与字段 DSL 的边界

`contains_clause` 在 `app/rules/dsl.py` 里只作用于**字段值**，`app/audit/clauses.py` 也是整篇文本级检查。
条款级的「必备要素/日期/措辞」需要 clause 作用域，因此放在 `app/legal_review/checks.py`（数据驱动的
`ELEMENTS/MARKERS` 正则表 + 日期解析），不强行塞进字段 DSL。三值语义保持一致：缺失 = finding、
未解析日期 = `needs_input`、解析不出 = 不猜。规则表是纯数据，可在测试里逐条断言。

### D8 · 出站脱敏与审计

条款文本出站前调用 `EgressPolicy.redact()`（同一套 redaction 规则与预算）；策略未加载或预算超限 → 该条款
`compose_error:redaction_unavailable`，不发送原文。报告含 `retrieval.queries/hits/layers`，
每个 clause check 含 `search_queries`，能回答「查了什么、命中多少、是否联网」。

脱敏有一个已知副作用：金额变成 `[redacted]` 后，模型可能把它读成「草稿缺字段」。两层处理：
SYSTEM_PROMPT 明确「`[redacted]` 是发送前移除的值，不是缺陷/占位符」，且要素齐全性由确定性检查在**原文**上判定，
模型不承担该判断。派生任务 9.5 记录「脱敏策略对法律分析的影响需要样本评测」。

## Risks / Trade-offs

### D9 · 实质性合规层用「词表 + 组合判定」，不用 RAG 兜底

用户要的不是"缺金额"，而是"武器出口到受制裁国家"这类实质风险。这类判断不能只靠法规语料（语料是贸易金融，
不含 EAR/ITAR/OFAC），也不能只靠模型（不可复核、会漏、会编）。因此：

- 词表（`app/legal_review/compliance.py`）：目的地（全面制裁 / 行业制裁两级）、受控货物（武器/导弹/无人机/
  核生化/两用物项/集束弹药/刑具/毒品/濒危物种）、跨境渠道（export/shipment/转运…）、规避措辞
  （第三国/拆单/现金/最终用户不明/壳公司…）。每条命中都带原文子串与 block 锚点。
- 组合判定（这是关键）：
  - 受控货物 × 全面制裁目的地 → `Critical`/`hard_block`（唯一由词表触发的硬阻断）；
  - 受控货物 × 行业制裁目的地 → `Critical`/`human_review`；
  - 受控货物 × 跨境渠道 → `Critical`/`human_review`（无许可证/分类/最终用户）；
  - 受控货物单独出现 → `Warning`/`human_review`；
  - 规避措辞 → `Warning`/`human_review`。
- 四个单元都进入计划（pass / finding / not_applicable），"没匹配到词"是一个结论，不是沉默。
- 模型仍是第二双眼睛：composer 的规则目录固定包含 `LEGAL-COMPLIANCE-*`，可补充未列入词表的品名/情形，
  但受同样的证据约束，且不能升级 severity/gate。
- 边界写进 finding 文本：**这是文本红黄线，不是许可或筛查结论**；真正的放行需要 denied-party 名单
  （OFAC SDN / BIS Entity List / EU / UN）、货物分类（ECCN/USML）与许可证判断。

### D10 · 要素目录按文种切换

保函要素（URDG/索赔单据/失效日）套在一份出口合同上会制造噪音，而噪音会淹掉真正的红黄线。因此
`detect_document_type()` 用小型启发式（保函/信用证/合同/未知）选择要素目录：
保函/信用证用 9 项，其他文种用 4 项（金额、币种、当事人、管辖）。文种写入 `snapshot.document_type`，
可用 `business_type` 覆盖。

## Risks / Trade-offs

- 条款上限 12：超长文档只扫前 12 段，报告显式 `truncated`；提高上限会线性增加延迟与成本。
- 模型成本：每条款一次 compose（≤12 次）+ 最多 1 次联网；`thinking` 默认关，深度分析需显式开启。
- 语料覆盖：语料以 CN/INT/US 为主，国际保函条款可能大量 `uncovered`；这是如实告知，不是 bug。
- 提交闸门：本期把 gate 返回给前端并在面板展示；`SubmitVersionDialog` 的硬拦截作为后续任务（见 tasks）。

## Migration / Rollout

1. `scope` 默认 `question`，旧前端与旧测试无需改动即可运行。
2. 部署：`./deploy/deploy.sh` 重建前端 + 重启后端；`runs/legal.db` 首次启动自动建表。
3. 回滚：前端切回旧 tab 或后端回退到上一版本；`runs/legal.db` 是新增文件，删除即可。