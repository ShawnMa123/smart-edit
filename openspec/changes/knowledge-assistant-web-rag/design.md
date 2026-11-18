# Design

## Context

现状（见 `proposal.md` 的 Why）：`AssistantService.execute_run` 依次执行 `analyze` → 证据构建 → `FixtureComposer.compose` → `review_answer` → `detect_conflicts` → publish。相关约束与可复用点：

| 事实 | 位置 | 对本设计的影响 |
|---|---|---|
| `RunStage` 只有 `analyzing/retrieving/composing/reviewing/publishing` | `app/assistant/schemas.py:22` | 需要新增 `screening` / `web_search` / `local_retrieval` 三个阶段，轮询端才能表达进度 |
| `RunCreate` 只有 question/selection/applicable_on/jurisdiction_codes/rule_version | `app/assistant/schemas.py:148` | 新增 `web_search: bool = False`，向后兼容 |
| `SourceType` 已含 `approved_web` | `app/assistant/schemas.py:43` | 联网证据无需新类型，只需约定 `locator` |
| `EvidenceCandidate(source_text/locator/effective_from/to/score)` | `app/assistant/ports.py:16` | 网页结果必须填满这些字段，后续引用与复核零改动 |
| `review_answer` 校验 excerpt ⊆ source_text、实体被支持、锚点匹配 | `app/assistant/pipeline.py:176` | 网页必须保存抓取正文片段，否则 claim 会被全部删除 |
| `detect_conflicts` 保留冲突、不自动裁决 | `app/assistant/domain/evidence.py:72` | 本地 vs 联网冲突可直接复用 |
| `Message.visibility` 支持 `redacted` | `app/assistant/schemas.py:36` | 联网轮次可只存实际外发查询 |
| `assert_safe_mode` 对 production 一律拒绝 | `app/assistant/adapters.py:26` | 接入真实 provider 后必须改为按 provider 白名单放行 |
| 运行时依赖无 HTTP 客户端（`httpx` 仅在 dev extra） | `pyproject.toml` | 需要新增运行时 `httpx` |
| `agent-knowledge` 的 `knowledge-assistant` 仍未归档 | `openspec/changes/agent-knowledge/specs/knowledge-assistant/` | 本 change 不修改它；三个新能力与其并列，避免归档顺序冲突 |

硬约束（来自 `AI_assistance_reqirement.md` §3.2 与 §4.1）：生成器没有数据库、网络、文档写入或任意工具；模型输出必须结构化并被复核。因此联网不能做成“给模型一张网卡”，只能做成**服务端检索端口**。

## Goals / Non-Goals

**Goals:**

- 把“可选联网 + 本地第二层 + 文档快照”统一成一条证据管线，复用既有引用、复核与冲突机制。
- 在任何外呼之前强制出站判定，默认最小化、失败关闭、可审计、用户可见。
- 用真实豆包（Ark）网关替换 fixture composer，同时保持 fixture 为默认测试路径与无配置时的安全行为。
- 让“哪些证据来自哪里、什么时候抓的、是否被拦”在回答里可读。

**Non-Goals:**

- 外部搜索服务商选型、配额、商用条款与页面正文抓取的合规评估。
- 内部 RAG 服务的真实端点、鉴权与索引治理（本 change 只交付端口、适配器骨架与契约测试）。
- 法律意见、合规结论、自动审批；以及任何“自动相信网页”的路径。
- 流式输出、模型自主规划、多轮工具调用、跨会话记忆。
- 修改 `knowledge-assistant` 既有要求（会话绑定、幂等、取消、发布原子性等保持原样）。

## Decisions

### D1 三层都实现为“证据提供者”，不新增答案路径

```
                    +---------------------------+
  RunCreate.web_search?  -->|  EgressPolicy.check     |
                    +------------+--------------+
                                 | allow/redact
              +------------------+-------------------+
              v                  v                   v
   WebSearchPort          RagPort (local layer)   Snapshot (existing)
   approved domains       lexical | http adapter  selection path
              |                  |                   |
              +----------> EvidenceBundle <----------+
                                 |
                    Composer (ModelGateway / fixture)
                                 |
                     review_answer + detect_conflicts
```

替代方案：让 composer 调用 `search` 工具。会直接违反 §3.2，且无法审计“模型到底发了什么”，不采用。

### D2 证据权威与顺序：本地已发布语料是规则事实的唯一来源

- 规则编号、版本、生效日、适用范围：只能由 `published` 语料（或未来经批准的 RAG 语料）支撑；联网结果 MUST NOT 支撑这类结论。
- 联网证据只用于“最新动态、公开解读、背景信息”；`support_level` 在有联网证据参与时最高为 `qualified`，纯联网证据时不得为 `strong`。
- 检索顺序默认 `local → web`，用户显式开启联网时可在同一次运行内合并；顺序不影响权威，只影响预算分配。
- 冲突一律保留（复用 `detect_conflicts`），并在 limitations 中说明“来源表述不一致”。

### D3 闸门位置与判定模型

闸门在 `analyze` 之后、任何外呼之前执行，**覆盖两类外呼**：联网检索与外部模型调用。判定输入不是原始 `RunCreate`，而是“本次将要外发的字段”：

```
EgressInput {
  question,                 // 原文，仅用于判定
  selection_text?,          // 仅用于判定，禁止外发
  entities[],               // 抽取出的敏感值
  candidate_query,          // 拟外发查询
  provider, purpose         // search | compose
}
EgressDecision {
  action: allow | redact | deny,
  reason_code,              // rule id，如 contains_selection / amount_present
  outbound_query?,          // allow/redact 后的最终查询
  policy_version
}
```

- **规则优先**：选中文本重叠、金额/编号/对手方正则、`{{variable}}`、超长粘贴、身份字段一律确定性判定。
- **模型兜底（可选）**：仅处理“语义上是否在问内部流程”这类模糊情形，输出必须落在枚举内；模型不可用 → 按拒绝处理。
- **失败关闭**：策略缺失、配置损坏、判定超时 → `deny`，并以可解释错误结束，而不是“默认允许”。

### D4 外发内容协议（最小化）

| 字段 | 外发 | 说明 |
|---|---|---|
| `outbound_query` | 允许 | 去实体后的查询，用户在外发前可见 |
| `locale` | 允许 | 影响检索语言 |
| `rule_id`（如 `URDG 758`） | 允许 | 公共标准编号，非客户信息 |
| `applicable_on` | 允许（日期） | 仅日期，不含交易信息 |
| `question` 原文 | 禁止 | 仅本地判定使用 |
| `selection.selected_text` | 禁止 | 明确是文档正文 |
| `entities{amount, party, reference, account}` | 禁止 | 抽取后从查询中移除 |
| `user_id / workspace_id / session_id / draft.text` | 禁止 | 任何请求都不得携带 |

### D5 真实模型网关（豆包/Ark）

- 传输：`httpx` 直连 OpenAI 兼容的 `/chat/completions`，不引入 SDK（避免锁定）。
- 配置：`SMART_EDIT_ASSISTANT_MODEL=doubao:<model>`（与 `SMART_EDIT_LLM` 并列），凭据走环境变量，禁止写入仓库。
- 输出：要求 JSON（`response_format` 或严格提示 + 解析），服务端用现有 Pydantic 模型校验；校验失败 → 运行失败并记录 `MODEL_OUTPUT_INVALID`，不做“尽力解析”。
- 模型只做三件事：查询分析（可继续用规则，模型为可选增强）、答案撰写、出站分类（可选）。三者都拿不到工具与网络。
- 未配置 → 保持现状（fixture composer 或明确失败），绝不静默换 provider。`assert_safe_mode` 从“production 一律拒绝”改为“按已批准的 provider 白名单放行”。

### D6 阶段、预算与降级

新增阶段：`screening` → `local_retrieval`（并行 `web_search`）→ `composing` → `reviewing`。预算初值（现有 deadline 120s）：

| 阶段 | 预算 | 超时行为 |
|---|---|---|
| screening | 1s | deny，运行失败并说明 |
| local_retrieval | 5s | 标记第二层失败，继续其他层或返回不足 |
| web_search | 8s | 标记联网失败，回答不得声称已联网核实 |
| composing | 30s | `timed_out`，不发布部分结果 |

联网与本地第二层可并行发起，但**两者都必须在闸门之后**；闸门只做一次（对最终 `outbound_query`），模型调用使用同一策略版本。

### D7 证据与引用契约

- `approved_web` 的 `locator`：`{url, domain, retrieved_at, provider, rank}`；`source_version` 用抓取时间戳（ISO-8601 UTC）。
- `source_text` 保存抓取正文的相关片段（上限 8k 字符），`excerpt` 仍由 `excerpt_for` 截取，保证 `review_answer` 的“摘录在原文中”可校验。
- citation id 用 `sha1(url|content_hash|chunk)`，同一 URL 不同抓取内容 → 不同 id，避免引用漂移。
- 去重：同一 URL 在同一次运行内只保留得分最高的一条；同一发布来源的重复片段在 bundle 层去重。

### D8 复核与等级裁剪

`review_answer` 原样复用（网页的 `source_text` 使其继续有效）；在其后追加一个确定性裁剪步骤：`web_only_claims → support_level ≤ qualified`，并强制追加 limitation “联网结果为未核验的第三方内容”。任何“联网已核实”的措辞都不得由模型自由生成，必须来自运行事实。

### D9 前端

`KnowledgePanel` 增加：开关（默认关，仅影响下一次提问）、出站预览（`Will send` / `Will not send`）、来源分区（Published / Web / Document）、网页条目（域名 · 抓取时间 · Unverified third-party）、拦截提示（`Web search blocked: the question contains document text`）。不改变现有 352px 单行 tab 与 `locale="en"` 约束。

### D10 审计与观测

新增事件：`egress_allowed`、`egress_blocked{reason_code}`、`web_search_failed{provider}`、`web_evidence_dropped{reason}`、`model_call{provider, model, task, ms}`。字段只含 ID、理由码、时间与哈希前缀；禁止写入正文、实体值与完整提示词。

### D11 测试策略

- 闸门：选中文本重叠、金额/编号、超长粘贴、配置缺失、策略超时、注入型问题 → deny/redact 的确定性用例。
- 联网层：fixture provider 覆盖命中、域名越界、超时、恶意网页（含“忽略之前指令”）、重复 URL。
- 分层：`local+web` 合并、web-only 等级上限、冲突保留、RAG 失败降级文案。
- 网关：合法 JSON、缺字段、枚举越界、非法 citation id、超时、未配置凭据 → 失败而非部分发布。
- e2e：默认关闭（无外呼）、开启后来源分区可见、拦截提示可见、历史消息已脱敏。

### D12 兼容与迁移

`web_search` 默认 `false`，旧客户端与旧会话行为不变；未配置模型 provider 时保持 fixture；不新增存储引擎、不做 DB schema 迁移（审计事件与字段为可选 JSON）。回滚 = 关闭 provider 与联网开关。

## Risks / Trade-offs

- **外发即披露** → allow-list + 最小化 + 审计 + 默认关闭；提供方条款与跨境传输需法务确认后才能在生产开启。
- **网页质量与 SEO 噪声** → 域名白名单 + rank 阈值 + 单次最多 5 条 + 只取正文片段。
- **Prompt injection** → 网页只作为不可信证据；模型无工具；复核只认摘录与实体，不认网页里的指令。
- **延迟** → 分层预算与并行；任何一层超时都降级并明说，不拖垮整体 deadline。
- **不可重放** → 保存抓取时间、URL 与内容哈希；同一运行内证据可复核。
- **成本** → 联网与模型都按运行计数，可在配置层限制每日配额（后续）。
- **合规误判** → 规则优先、模型兜底；误拒会降低体验但不会泄露，误放才会，所以默认偏向拒绝。

## Migration Plan

1. 先落端口与 fixture 适配器（web/RAG/模型），行为与现在一致（联网关闭）。
2. 打开闸门与审计（仍无外呼）。
3. 配置真实模型 provider，先只用于 composing。
4. 配置真实联网 provider + allow-list，灰度开启。

回滚：关闭 `web_search` 默认值、移除 provider 配置即可回到当前行为。

## Open Questions

- 豆包 key 是否包含“联网插件/搜索增强”；若包含，是否允许其把查询转发给字节的搜索后端（影响 allow-list 与出站审计粒度）。不改变本设计的端口与任务拆分。
- 内部 RAG 服务的实际 endpoint、鉴权与返回字段；适配器骨架已就绪，缺的只是配置与映射。
- allowed domains 与禁止字段清单的维护人、审批流程与更新频率。
历史消息：联网轮次以 `visibility="redacted"` 保存 `outbound_query`；审计只记录理由码、提供方与查询的不可逆摘要（`sha256` 前缀），不记录正文。

按外呼类型区分（egress spec 的"按外呼类型最小化"）：

- `purpose=search`：只允许 `outbound_query` + `locale` + 公共规则编号 + 日期；文档内容与实体一律拒绝。
- `purpose=compose`：仅当提供方在配置中登记为 `approved_processor` 时，允许发送问题与证据包（含 `document_snapshot` 片段）；仍禁止会话身份、附件原文件与未入选证据。
- 未登记提供方：拒绝并给出可解释错误，不静默改用本地 composer 或另一提供方。