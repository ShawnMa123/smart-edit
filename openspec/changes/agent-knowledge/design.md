# Design

## Context

见 `proposal.md` 的 Why。需求真相源是 `AI_assistance_reqirement.md`（KA-01～KA-14、KT-01～KT-21、§13.3 I1–I5）与 `Requirements.md` §8。当前仓库是 POC：

- `/runs` → `parse/extract/normalize/audit` 同步 stage；`EditState` 冻结；fixture LLM；JSON `runs/`；无鉴权/数据库/Worker；
- `AssistantPanel` 的 Knowledge Q&A 仍是 `not implemented`；
- `agent-regulatory`（0/51）已规划 `knowledge/*.md` + 内存向量检索，但未实现；
- Orchestrator 实施文档有 `KnowledgeWorker` / `AnswerPayload`，仓库里没有。

本设计把 A 做成 **C 的第一段薄纵切**：外部合同、领域规则、权限与证据不变量按 C 实现；Adapter、存储、执行器、知识导入与 UI 深度可以先简。

## Goals / Non-Goals

**Goals:**

- 独立 `app/assistant/` 模块与 `/assistant/*` API，DTO 与 C 一致；即使当前进程内执行，也保留 `202 + Run + 轮询` 合同。
- Run 状态机、幂等、单会话一个活跃 Run、取消/超时/终态竞争。
- Port/Adapter 边界：身份/授权、快照、存储、检索、模型、审计、时钟/ID、知识管理；A 只提供 local/fake。
- SQLite 存储，表与字段镜像未来 PostgreSQL；所有访问经 repository 接口。
- 共享知识层 `app/knowledge/`：来源/版本/分块、发布状态、生效期、独立审核、原子发布/撤回；只检索 `published` 且当前授权/有效的版本。
- 真实管线 + 代码 Reviewer：Claim 级引用、摘录/实体覆盖、support_level、弃答/澄清/转交；fixture 只替换生成器。
- 服务端权限/快照绑定/撤权 redacted；Knowledge Q&A tab 可用，Automation/Legal 仍标未实现。

**Non-Goals:**

- PostgreSQL、真实 Worker/队列、真实身份/组织/ACL、宿主快照/附件、真实模型/向量/重排、受控联网、语音/截图、导出、知识管理 UI。
- 修改 `EditState` / `AGENT_IDS` / 现有 audit 链路；知识助手不写正文、不审批、不创建编辑任务。
- 声称合成语料是真实法规，或 fixture 运行是生产模型运行。

## Decisions

### D1. 独立模块 + 规格 DTO，A 也用 `202 + Run + 轮询`

新增 `app/assistant/` 与 `app/api/assistant.py` router，路径沿用规格：`/assistant/sessions`、`/sessions/{id}/runs`、`/runs/{id}`、`/messages`、`/messages/{id}/citations/{cid}`、`/messages/{id}/feedback`。

*为什么不用 `POST /assistant/ask`：* 那会成为一次破坏性迁移；C 的 Worker/取消/历史都要求 Run。*为什么不做成第 5 个 stage：* `EditState` 是文档审计状态，装不下 Session/Message/Citation/Feedback；会动冻结契约。*A 的实现：* 创建 Run 后由进程内执行器处理，客户端仍轮询；第一次轮询通常已 `succeeded`，但合同不变。

### D2. Port / Adapter，production 遇 Fake 必须失败关闭

| Port | A 的 local/fake | C 的替换 |
|---|---|---|
| `IdentityPort` / `AuthorizationPort` | 固定 principal/workspace；测试可切两个用户 | 宿主身份、组织、授权版本 |
| `SnapshotPort` | 本地 snapshot 注册表（POC 专用 endpoint） | 宿主不可变快照/附件服务 |
| `StorePort` | SQLite repositories | PostgreSQL repositories |
| `RetrieverPort` | 词法检索 | 混合向量/词法 + 重排 |
| `ModelGateway` | fixture/确定性 Composer | 批准模型 + 结构化输出 |
| `AuditPort` | SQLite 审计表/事件 | 审计平台/Outbox |
| `KnowledgeAdminPort` | 最小 CLI/fixture 种子 | 导入/审核/管理端 API |

*为什么：* C 的迁移成本主要取决于业务代码是否直接依赖 Fake/框架。*替代方案：* 直接写 FastAPI handler 调 SQLite/固定答案——最快，但 C 等于重写。

### D3. SQLite 表镜像 PostgreSQL，repository 隔离

用标准库 `sqlite3`，表名/列名沿用规格 §7.3：`assistant_sessions`、`assistant_messages`、`assistant_runs`、`assistant_dependencies`、`assistant_citations`、`assistant_feedback`、`knowledge_sources`、`knowledge_versions`、`knowledge_chunks`、`idempotency_records`、`outbox_events`。每张表只经 repository 访问；业务层不写 SQL。

*为什么不用 JSON：* 未来 PG 需要表/事务/唯一约束；SQLite 现在就能表达，迁移是换实现而非重做模型。*替代方案：* JSON 文件最简单，但迁移要重新建 schema 与约束，容易丢字段。

### D4. Run 状态机与执行器

`queued → running → succeeded | failed | cancelled | timed_out`；`stage` 记录 `resolving_context/analyzing/retrieving/composing/reviewing/publishing/completed/...`。创建 Run 返回 202；同一 Session 只允许一个 `queued/running`；幂等键 + 请求摘要；取消/超时/发布用 compare-and-set；迟到结果不得覆盖终态。

A 用进程内执行器（FastAPI `BackgroundTasks` 或专用线程）+ 截止时间检查；若进程重启，启动时把过期 `queued/running` 标为 `failed/timed_out`。*C：* 替换为 Worker/租约/fencing token，不改 API/状态机。

### D5. 共享知识层与最小发布闭环

`app/knowledge/` 由本 change 拥有，`agent-regulatory` 后续作为只读消费者：

- `knowledge_sources`：`source_id`、类型、发布者、语言、scope/ACL、组织、内容级别、许可；
- `knowledge_versions`：版本、状态（`processing/pending_review/published/superseded/withdrawn`）、生效区间、`submitted_by`/`reviewed_by`、文件摘要；
- `knowledge_chunks`：章节/页码/表格边界、标题路径、正文、定位；
- 发布：所有 chunk 完成后，`reviewed_by != submitted_by` 的审核决定原子切换发布指针；撤回立即影响检索与引用；
- 检索：先过滤 `published`、当前授权、生效区间（`[from, to)`，无 `to` 为开放），再词法召回；`superseded` 只用于明确历史问题。

A 的入口是最小 CLI/fixture 种子：导入合成语料 → `pending_review` → 第二个 fake reviewer 批准 → `published`；不建管理端 UI/完整导入 API。*为什么保留状态字段：* 如果 A 把语料当“永远发布”，C 的知识审核会改变检索结果与全部测试。

### D6. 检索：A 词法，C 混合

A 的 `RetrieverPort` 用确定性词法召回：英文 casefold 词项 + 中文二元组/关键词，按 chunk 命中数与字段加权排序；只返回授权、已发布、当前有效的 chunk；`score` 只用于排序，**不能展示为回答置信度**。查询“最新”时显式使用服务端当前日期并写进答案；历史规则按 `applicable_on` 选择版本。

*为什么不上向量/重排：* 当前没有批准 embedding/向量服务，且 A 的合成语料小；*C：* 同一个 Port 换成混合检索 + RRF + 重排，领域层不变。*替代方案：* 直接接一个本地向量库——增加依赖与迁移面，收益不成比例。

### D7. QueryAnalyzer：确定性路由，模型只做可选增强

意图枚举固定为 `product_faq | trade_rule_explanation | document_explanation | out_of_scope`。A 用规则/关键词/上下文（是否有快照、是否选中文本、是否提到规则号/法域/日期）决定路由；缺规则版本/法域/适用日期且会改变答案时输出 `needs_clarification`；要求修改/审批/完整审查时输出 `needs_handoff`。分类结果不得越出枚举，不得凭置信度自动执行副作用。

*C：* 可以用模型辅助分类，但输出仍需 Schema 校验；跨组编排由上层 Orchestrator 负责，知识助手不创建第二个编排器。

### D8. Composer + 代码 Reviewer：fixture 只替换生成器

Composer 输出 `claims[]`（每条 `fact | interpretation`）、`citation_ids[]`、`limitations[]`、`clarification_questions[]` 与 `outcome`。A 用 fixture/确定性生成器；**Reviewer 是真实的代码**：

1. 每个 `fact` Claim 至少一个 citation，且 citation 必须来自本次 `EvidenceBundle`；
2. 引用摘录必须与来源 chunk 的实际文本匹配；
3. 金额/日期/规则号/公司名等关键实体必须出现在被引原文；
4. Claim 与引用必须有可解释的支持关系（A 用摘录/实体覆盖，C 可加语义复核）；
5. `support_level` 由检查结果计算，不由模型自报；失败最多修复一次，仍失败则删除无依据 Claim 或 `abstain`。

*为什么：* 如果 fixture 直接返回“完美答案”，C 的 Reviewer 等于不存在。A 必须用负例（伪造 citation / 引用不支持 Claim）证明 Reviewer 会拦截。*不记录*模型隐式思维链；只记录结构化问题代码与结论。

### D9. Citation / EvidenceDetail：只给授权摘录与定位

Citation 只含 `source_type / title / source_version / locator`；`EvidenceDetail` 返回获准摘录、定位、`effective_from/to`、`retrieved_at`（仅真实联网时）。不返回对象存储地址、未授权全文或模型生成的 URL。文档引用定位到快照节点/字符区间；选区偏移用 Unicode code point 半开区间，并与快照原文切片**完全匹配**，否则 `ANCHOR_MISMATCH`，不静默改成最近文本。OCR 待确认值在回答里附“请核对原件”。

### D10. 权限与快照：A 用 Fake，但检查在服务端

`AuthorizationPort` 由服务端计算 principal/workspace/角色/授权版本；客户端不能声明 owner/role/ACL。Session 绑定 owner；读取/运行/引用/反馈都校验 owner 与依赖；跨用户/非所有者统一 404；撤权或来源撤回后消息 `redacted`。A 提供两个 fake principal 供测试，证明隔离不是 UI 隐藏。

`SnapshotPort` 在 A 用本地注册表：前端把当前 version digest/正文注册为不可变 snapshot（POC 专用 `POST /assistant/snapshots`，C 移除并接宿主快照服务）；CreateSession 只引用 snapshot ID。这样 CreateSession 合同不变，C 只换 Adapter。

### D11. 前端：Knowledge Q&A 面板

`AssistantPanel` 把 `knowledge` 标为 implemented，新增 `KnowledgePanel`：

- 首次提问时基于当前编辑器 version digest 创建 snapshot + session；显示“绑定快照/旧版本”状态；
- 问题框、可选选区、Run 轮询与取消、错误码文案；
- Answer：outcome、support_level、claims、citations、limitations、clarification questions、handoff 建议；
- 引用卡片打开 EvidenceDetail；反馈（helpful/not_helpful + 类别）；fixture-backed 横幅；旧版本时提示新建会话；
- Automation / Legal 继续显示 `not implemented`，不渲染示例答案。

`document-editor` 的 delta 见 `specs/document-editor/spec.md`。

### D12. 测试与 A → C 升级

A 的测试分三层：纯领域（路由/证据/Reviewer/状态机/权限）、repository/Adapter 合同（SQLite + fake）、HTTP/UI（会话/轮询/取消/引用/反馈/跨用户 404）。KT 矩阵先覆盖 KT-01/02/03/05/06/07/08/09/10/11/12/13/14/15/16/17/18/21；KT-04/19/20 视附件/审计/性能实现深度。

A → C 的映射：

```
FakeIdentity/Snapshot  -> 宿主 Adapter        （只换 Adapter）
SQLite repositories    -> PostgreSQL           （只换 StorePort 实现 + 迁移）
进程内执行器            -> Worker/队列/租约      （只换 Runner，状态机不变）
词法 Retriever         -> 混合/向量/重排        （只换 RetrieverPort）
Fixture Composer       -> 批准 ModelGateway     （只换生成器，Reviewer 不变）
最小知识 CLI/种子       -> 导入/审核/管理端 API   （读路径与状态不变）
轮询 UI                -> SSE/历史/观测          （API 合同不变）
```

C 升级的通道表（K01–K15）、实施顺序、触发条件、待决策与反模式见 [`TBD-upgrade-to-c.md`](TBD-upgrade-to-c.md)。本 design 只固定 A 的接缝；TBD 记录后续如何换实现。

### D13. Phase 1 合成语料扩展：扩现有 source，不新增规则 source

Phase 1 只提升演示与评测的覆盖，不改变合同、状态机、检索或 Reviewer。做法与边界：

- **扩展现有 3 个 source**（`KS-PRODUCT-001`、`KS-RULES-001`、`KS-POLICY-001`）到 12/12/8 chunks，而不是新增第二个 URDG source。原因：`detect_conflicts()` 会把“不同 source 对同一 rule entity 的不同表述”判为冲突并 `unable_to_assess`；新增第二份规则摘要会让 demo 频繁弃答。
- **版本升级**：内容变化必须发新版本（`demo-2` / `KV-*-v2`），旧版本可 `superseded`/`withdrawn`；本地旧库要么删除重建，要么走 CLI `import → review`，不能原地修改已发布版本。
- **条款级切块**：规则按条（article）切，产品/政策按小节切；保留 `section/page/title_path/locator`，一条 chunk 能独立回答问题；表格按行拆，定义/例外/期限不拆散。
- **显式合成**：标题、正文、`publisher`、`license_reference` 都标 synthetic/演示用/非官方；不复制 ICC/SWIFT/银行原文，不出现真实银行名。
- **评测**：保留原 20 题作为基线，新增 5 题到 25；指标仍为 outcome/citation/clarification；不降低阈值。新增 chunk 若改变既有题的期望引用，必须在任务中显式改题目/期望并记录原因，不能把“检索变差”藏进阈值。
- **冲突与权威**：Phase 1 不引入 authority/precedence；内部政策与规则摘要避免同时出现同一 rule entity 的相似表述。多来源权威、真实许可文本、PDF/URL 导入、chunk 级语言均不在 Phase 1，留给后续 change。

### D14. 并行语言语料与本地 fixture 补种（由 knowledge-onboarding 触发）

`knowledge-onboarding` 增加英文镜像语料与英文 onboarding，会暴露两个知识层事实：

- **语言隔离**：同一主题存在中文/英文 source 时，一个 Run 只能使用与 `plan.language` 一致的 source。否则英文问题可能引用中文 chunk，或中英文同一 rule entity 被 `detect_conflicts()` 判为冲突。检索先按 language 过滤，再按 `capability_help`/help source 过滤；不改变 Answer/Reviewer 合同。
- **本地补种**：`build_services` 当前只在 `knowledge_count()==0` 时 seed。新增英文/帮助 source 后，旧 `runs/assistant.db` 永远不会得到它们，导致能力问题落到 `insufficient_evidence`。local/test 启动必须补种缺失 source、升级 fixture version，已存在的相同 source/version 跳过；补种失败应明确报错，生产模式不补种。

行为契约在 `knowledge-onboarding` spec 的“并行语言来源不得混用”和“本地/测试 fixture 必须补齐”中；本 change 只记录并实现底层 retrieval/seed 接缝。

## Risks / Trade-offs

- **[合成语料被当成法律结论]** → 语料/回答标 `synthetic/fixture-backed`；只做解释与转交，不出“合法/可开立”结论；DEMO 与 UI 明确声明。
- **[Fake Adapter 泄漏到生产]** → 启动时检查模式；production 检测到 Fake/合成源即失败关闭；测试覆盖。
- **[中文词法检索召回不足]** → 语料规模小且问题集受控；`RetrieverPort` 预留；C 换混合检索；A 的评测注明未做向量/重排。
- **[选区偏移与编辑器不一致]** → code point 偏移 + 快照原文切片严格匹配；不匹配报 `ANCHOR_MISMATCH`；A 先支持单节点选区。
- **[SQLite 并发/重启]** → 单进程 + 每 Session 锁；启动恢复把过期运行标 failed/timed_out；C 换 PG/Worker。
- **[取消/超时与发布竞争]** → 状态转换用 compare-and-set/行锁；迟到结果不得覆盖终态。
- **[知识层与 agent-regulatory 重复]** → 本 change 拥有 `app/knowledge/`；法规组只读消费；在它的 follow-up 里同步，不复制语料。
- **[A 被误认为 C]** → proposal/design/UI 明确“未做 PG/Worker/真实鉴权/模型”；DoD 不含这些项。

## Migration Plan

1. **合同与 Port**：DTO/Schema、状态机、错误码、Port 接口、模式校验；不接 UI/模型即可测试。
2. **存储与 Fake**：SQLite repositories + fake Identity/Snapshot/Audit；启动恢复；幂等。
3. **知识层**：合成语料、来源/版本/分块、最小审核/发布 CLI、检索过滤。
4. **管线**：QueryAnalyzer → Retriever → EvidenceBuilder → Composer → Reviewer → Publisher；负例测试。
5. **API 与执行**：Session/Run/Message/Citation/Feedback；202 + 轮询 + 取消/超时。
6. **UI**：KnowledgePanel、AssistantPanel tab、快照绑定/引用/反馈；`document-editor` delta。
7. **C 升级**：PG repositories + 迁移；Worker/队列；真实身份/快照；批准模型/混合检索；知识管理 API/UI；SSE/观测。DTO、领域规则、Reviewer、权限判定不变。

回滚：关闭 `/assistant` router 与 Knowledge tab 即回到当前状态；SQLite 独立于 `EditState`/`runs/`，无数据迁移；不触碰冻结契约。

## Open Questions

1. **知识层所有权** —— 建议本 change 拥有 `app/knowledge/`，`agent-regulatory` 作为只读消费者；需要与该 change 的 owner 确认，避免两套语料。
2. **真实模型/embedding 的批准与驻留** —— P1；A 用 fixture/词法，C 的 Provider 待数据治理批准。
3. **双语检索质量** —— A 只承诺受控合成问题集；真实中文语料的 Recall 需在 C 的离线评测中建立基线。
4. **附件/OCR 待确认值** —— A 先支持已解析文档/快照；附件引用与 OCR 待确认提示按 `document-import` 的现有数据接入，深度待样本确认。