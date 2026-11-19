# Design

## Context

动机见 `proposal.md` — Why。塑造本设计的仓库事实（均已核实）：

- **法规腿已实现且被测试覆盖**：`StatuteRetriever`（`POST {MERCATORIA_BASE_URL}/v1/retrieve`，body `{queries, top_k, filters}`）、可用性判定 `judge()`（`confidence=low`、`top score<0.6`、`zero_reason`、`requested_uncovered`、`superseded`）、`_run_local()` 的"法规优先、不可用回退本地"、`_annotate_statute()` 的四种失败文案、前端 `statuteBadge()`/`statuteNotice()` 均已完成。`knowledge-statute-retrieval` 23/23、`statute-recall` 9/9。
- **默认关闭**：`STATUTE_ENV`/`STATUTE_BASE_URL_ENV`/`STATUTE_TOKEN_ENV` 三者缺一即不构造，启动日志为 `statute=False`；本机 `.env` 未配置，故 `run_cdd1dd588e31` 只跑了 `local` 层。
- **既有实测记录**：`statute-recall/tasks.md` 4.1 记有"`guarantee是什么` 命中最高法《独立保函规定》并被引用"，说明**当前扩展词表（含 `URDG 758`）在无法域过滤时已能通过闸门**；但"带 `jurisdictions` 过滤"这一维从未测过。
- **出站策略覆盖三种用途**：`Purpose = Literal["search","compose","tool_search"]`，`check()` 对 `compose` 只校验处理器批准、对 `search`/`tool_search` 做脱敏与 40 字选中重叠拒绝；**法规调用不在此列**，且 `design.md:11`（knowledge-statute-retrieval）写明"任何外部调用前过闸"。
- **来源标记只有五项**：`Route = Literal["published","document","general_web","handoff","none"]`；法规答案目前落 `published`，无法与本地语料答案区分。
- **判定层有离线评测**：`scripts/statute_eval.py` + `fixtures/assistant/statute_eval.json`（15 例）只覆盖 `judge()`，不覆盖 HTTP 映射、引用 locator 与端到端。
- **前置缺陷**：`analyze()` 把"存在选中文本"当作 `document_explanation` 的充分条件，导致选中 `guarantee` 时问题不进法规腿（工作区已有修复与单测，尚未提交）。

## Goals / Non-Goals

**Goals:**

- 让"这次是否调用了 `/v1/retrieve`、发出的是什么、回来几条、为什么采用/不采用"在日志、审计、运行结果与界面**四处一致可查**。
- 法规调用与网页检索共用同一套出站判定，且判定失败按 fail-closed 处理。
- 无网络、无隧道时仍能用录制响应证明上述链路。
- 把"带法域/不带法域"的实测差异固化成可复用的数据，供下一轮决定是否改查询构造。

**Non-Goals:**

- 不改变召回策略：`definition` 子意图、定义类不发 `jurisdictions`、扩展词分档、阈值调整均不在本 change。
- 不改变证据合成：法规可用时仍独占证据，不与本地语料合并。
- 不引入 `/v1/chat`、查询改写、多路检索或 compose 后润色。
- 不改数据库结构与既有 API 字段语义（只做枚举增量）。

## Decisions

### D1 · 意图前置：选中文本只有在"指向它"或"没有主题"时才算文档解释

`document_explanation` 成立的充分条件改为二选一：问题含指向性词（`这段/这句/本文/选中/this passage/this clause…`），或问题本身不含规则/产品主题词。判定复用现有确定性词表（`_RULE`、`_PRODUCT`、`entities`），不引入模型。

- 备选：把选择权重化（置信度打分）—— 否决：无法在线性词表层解释，且 violation 风险高于收益。
- 备选：保持现状，靠前端"未选中才能提问"—— 否决：编辑器里永远可能有选中，等于关掉法规腿。
- 代价：`请解释这段条款` 这类问题仍走文档路径（含"这段"），语义正确；`guarantee 在贸易里说什么` 改走规则路径，这正是目标。

### D2 · 出站闸：新增用途 `statute`，作用在"扩展前"的用户输入

`Purpose` 增加 `statute`，与 `search` 共用脱敏与选中重叠规则，额外要求"策略已加载"；判定在 `_run_local()` 内、调用 `StatuteRetriever` 之前完成，使用 `plan.question` + `payload.selection.selected_text` + `plan.entities`，把判定后的查询传给适配器（新增可选参数或浅拷贝 plan），扩展词仍由适配器追加。

- 为什么在扩展前：`expand_terms()` 的输入来自配置，不是用户内容；先扩展再送检会把配置术语混进"用户输入"，也会让 query digest 失去"用户到底发了什么"的含义。
- 为什么新增用途而不是复用 `search`：用途要进审计，`search` 目前语义是"网页检索"；`statute` 需要能被单独统计与单独收紧（例如未来允许内网服务跳过域名校验）。
- host 校验：`MERCATORIA_BASE_URL` 常为 SSH 隧道 `127.0.0.1`，`allowed_domains` 对它无意义。判定 SHALL 跳过域名校验，但 MUST 在审计里写明 `provider="statute"`；域名白名单只对 `search`/`tool_search` 生效。
- 拒绝路径：不调用、`RetrievalLayer(status="blocked", detail=reason)`、`_annotate_statute()` 追加"因出站策略未查询法规"文案；前端 `statuteNotice()` 增加 `blocked:*` 分支。
- 备选：在适配器内部过闸 —— 否决：适配器拿不到 selection，也无法写运行级审计。
- 备选：不补闸，只补"调用已发生"的审计 —— 否决：与 design.md:11 的既有不变量冲突，且敏感内容会原样外发。

### D3 · 来源标记由引用推导，不由模型自述

`_route_for()` 增加：答案 `citations` 含 `source_type=="statute"` → `route="statute"`；其余规则不变。前端 `AnswerRoute` 同步，并把 "Answered from published sources" 的判据扩展到 `statute`（改为"来自法规/已发布来源"或直接不显示该行）。

- 备选：新增 `source_layers` 字段 —— 否决：API 扩散，`route` 已能表达"这次靠什么答的"。
- 代价：`KnowledgePanel` 有一条依赖 `route==='published'` 的提示，需要同步改判据并补组件测试。

### D4 · 回放契约：一份真实响应 fixture + `MockTransport` 端到端

新增 `fixtures/assistant/mercatoria_guarantee.json`，保存一次真实 `/v1/retrieve` 原始响应（`chunks[]`、`diagnostics`、`field_matches`、`corpus`）。测试用 `httpx.MockTransport` 注入 `StatuteRetriever`，再以 `make_service(statute=...)` 跑完整 run，断言四件事：

1. 请求体中的 `queries` 含扩展词、`filters` 与 payload 一致（法域/交易日）；
2. `judge()` 的判定与录制一致（可用，或 `low_confidence` + `hits`）；
3. 引用 `locator` 含 `doc_id/article_label/jurisdiction/effective_from`；
4. 检索层记录（`statute` 的 `status/detail/hits`）与最终 `route` 一致。

- 是否需要第二份样本：若首份录制为低置信，另存一份高置信样本，分别覆盖"采用"与"被拒"两条分支（spec 要求两种结局都可测）。
- 备选：只测 `judge()`（现状）—— 否决：证明不了"调用发生了"。

### D5 · 校准网格是本次交付物，不是本次改动

Phase 1 用真实服务跑 `{原句 / +定义词 / +定义词+URDG} × {带法域 / 不带法域}` 六格，记录 `confidence`、`top chunk`（`doc_id/article_label`）、`score`、`requested_uncovered`，写进本文档 Findings。**本 change 不据此改代码**；若某格稳定优于现状，下一轮再改 `query_expansion`/`build_filters`。

- 为什么不在本轮顺手改：`statute-recall` 4.1 已证明现有表能命中并引用；在缺少"带法域"数据时改表，等于用未测参数覆盖已测结论。

### D6 · 启用方式不变：三个变量 + fail-fast

继续使用 `SMART_EDIT_STATUTE`、`MERCATORIA_BASE_URL`、`MERCATORIA_API_TOKEN`，缺一启动失败（已有实现与单测）。本 change 只把步骤、隧道与验收命令写进 `how_to_use.md`，不改解析逻辑。

## Risks / Trade-offs

- [新闸把既有 `StubStatute` 用例判成拒绝] → 预期行为；为这些用例注入 `demo_policy()`，并在 tasks 中显式列出该连带修改。
- [部署侧缺少出站策略文件时法规腿整体不可用] → `knowledge.sample.json` 随仓库发布；日志与文案明确 `policy_unavailable`，不静默降级。
- [录制 fixture 含法规原文，存在许可/长度风险] → 只录 `excerpt` 长度范围内的文本，并在 fixture 顶部注明来源与用途；全文不落库（沿用既有约定）。
- [来源标记新增枚举值影响前端渲染] → 组件测试覆盖 `statute` 与 `published` 两种来源的提示文案。
- [法规调用与合成摘要对同一规则措辞不同] → 冲突检测已按 `source_type` 分层（`detect_conflicts`），不会误报。

## Migration Plan

1. 代码与测试先行（D1-D4），默认关闭下行为不变，全量回归。
2. 部署开启：配置三个变量 + 隧道，验证启动日志 `statute=True`、一次 `什么是guarantee` 的层记录与审计。
3. 录制真实响应 → 生成 fixture → 回放测试入 CI。
4. 校准六格网格 → 写 Findings（不改代码）。
5. 回滚：任一环节出现问题，清空 `SMART_EDIT_STATUTE` 即回到词法-only；无 schema 变更、无数据迁移。

## Findings

本 change 的交付物之一：真实服务上的 3×2 校准结果（Phase 1 填写，**不据此改代码**）。

**环境**（2026-11-18，经 `team04-pg` 隧道 `127.0.0.1:18080 → mercatoria:8080`）：index `20261114-151703-157038-21cc6c676382`，143 篇 / 11,562 chunks，embedding `qwen3.7-text-embedding`，rerank `gte-rerank-v2` 已启用，`top_k=5`。表中"定义词"= 追加 `定义`；"`URDG 758`"= 再追加规则号；法域过滤为 `filters.jurisdictions=["WTO"]`。`requested_uncovered` 六格均为空（`jurisdictions: []`、`applies_to: []`），可排除"未覆盖"。

| 查询 | 法域过滤 | confidence | top chunk（doc_id / article_label） | score | requested_uncovered | 结论 |
|---|---|---|---|---|---|---|
| `什么是guarantee` | 不带 | low | `eu-ucc-2013` / Article 92 | 1.0 | 空 | 不采用：命中的是 EU 合同解除条款，与保函无关 |
| `什么是guarantee 定义` | 不带 | low | `eu-ucc-2013` / Article 92 | 1.0 | 空 | 追加"定义"无效 |
| `什么是guarantee 定义 URDG 758` | 不带 | low | `eu-ucc-2013` / Article 92 | 0.792734 | 空 | 追加规则号仍然无效 |
| `什么是guarantee` | 带 `WTO` | low | `wto-tfa` / Article 11 | 0.885325 | 空 | 不采用：法域把召回锁进 WTO，偏离保函 |
| `什么是guarantee 定义` | 带 `WTO` | low | `wto-tfa` / Article 11 | 0.921533 | 空 | 同上 |
| `什么是guarantee 定义 URDG 758` | 带 `WTO` | low | `wto-tfa` / Article 11 | 0.955185 | 空 | 同上 |
| *参考：现状真实请求* `什么是guarantee 独立保函 见索即付保函 demand guarantee URDG 758`（`knowledge.sample.json` 的扩展词表，不带法域） | 不带 | **medium** | `cn-independent-guarantee-2020` / 第一条 | 0.847079 | 空 | **可用**：引用《最高人民法院关于审理独立保函纠纷案件若干问题的规定》第一条 |

附：验收第②条所用的"被拒"样本为 `URDG 758 第 20 条对索赔有什么要求？`（该问句不命中扩展词表，原样发出）→ `low`，5 条命中，top 仍为 `cn-independent-guarantee-2020` / 第一条（0.934574），因此被拒后由本地已发布语料作答。

**判读**：

1. **带法域不可行（对本问题族）**：`WTO` 过滤后六格 top chunk 全部是 `wto-tfa` Article 11（贸易便利化），`confidence` 全部 `low`；不带法域的原句同样 `low`，top 是 `eu-ucc-2013` Article 92（合同解除）。两组的差异来自过滤，不来自"带法域更准"。
2. **`requested_uncovered` 为空**，说明问题不在覆盖范围，而在**查询/召回**：裸句、加"定义"、加规则号都不能把保函条文提到前面。
3. **真正起作用的是已发布的扩展词表**：同一句加 `独立保函 / 见索即付保函 / demand guarantee / URDG 758` 后 → `medium`、`cn-independent-guarantee-2020` 第一条、0.847 → 通过闸门并被引用。这与 `statute-recall` 4.1 的既有记录一致。
4. **对预登记判读规则的修正**：原规则"全部 `low` → 下一轮优先改 `build_filters`（定义类不发法域）"**未被本次数据支持**——不带法域也全是 `low`，而保留现状过滤 + 扩展词即可用。下一轮若改，优先"扩展词分档/查询构造"，不要给定义类问题加/去法域，也不要放宽 `0.6` / `confidence=low` 闸门。
5. 原始响应已作为回放契约落库：`fixtures/assistant/mercatoria_guarantee.json`（扩展词请求，可用）与 `fixtures/assistant/mercatoria_guarantee_low.json`（原句请求，低置信），由 `tests/test_statute_replay.py` 离线重放。

## Open Questions

- Mercatoria 允许展示的原文长度与许可范围（沿用"只展示 excerpt + locator"的临时约定）。
- `MERCATORIA_*` token 的轮换与责任人。
- 下一轮是否引入"定义类问题不发法域过滤"与"扩展词分档"—— 由 Findings 决定。
- `_should_try_statute()` 目前对"显式声明了法域的产品问题"也会调用法规服务，是否需要收紧（与本 change 目标无关，但会影响时延与噪声）。
- **新增观察（2026-11-18，`guarantee在wto定义是什么`）**：Mercatoria 判定为"可用"（CN 独立保函司法解释，`medium`），但模型以"证据不是 WTO 官方规则"拒答，最终 `outcome=insufficient_evidence`、`route=none`；同时法域过滤只来自界面 chips，问题文本里的 `wto` 不会进入 `filters`。下一轮需决定：是否从问题文本解析法域，以及是否在"法规可用但与问题所指法域/主题不符"时回退本地/RAG，而不是直接交给模型拒答。