# Proposal

## Why

知识助手是四个能力组里唯一还没有任何实现的组：右栏的 `Knowledge Q&A` 仍是 `not implemented`，`AI_assistance_reqirement.md` 的 P0（Session/Run、Claim 级引用、support_level、澄清/弃答/转交、权限过滤、知识发布/撤回、反馈）没有任何代码承载。现在直接做生产形态会同时引入 PostgreSQL、Worker、宿主身份/快照和真实模型，周期与依赖都不可控。

所以先做 **A 方案（POC 薄纵切）**，但每一条边界都按 C（生产 P0）的接缝设计：**现在换实现，未来换 Adapter，而不是重写业务**。这样下一轮加 PostgreSQL、知识审核、真实鉴权/快照/模型/Worker 时，外部合同、领域规则和测试基线都能继续用。

## What Changes

- **新增独立的 `app/assistant/` 模块与 `/assistant/*` API**，按 `AI_assistance_reqirement.md` 第 7–8 节的 Session / Run / Message / Answer / Citation / Feedback / Error DTO 实现；**即使当前执行是同步/进程内，也保留 `202 RunAccepted + 轮询` 的对外合同**，C 只替换执行器。
- **Run 状态机**：`queued | running | succeeded | failed | cancelled | timed_out` + `stage`；幂等键、每 Session 一个活跃 Run、取消/超时/迟到结果不覆盖终态。A 用进程内执行器 + 截止时间检查；C 换 Worker/租约/fencing。
- **Port / Adapter 边界**（A 只提供 local/fake，production 检测到 fake 必须失败关闭）：
  - `IdentityPort` / `AuthorizationPort`（principal、workspace、角色、授权版本）
  - `SnapshotPort`（不可变文档快照；A 用本地 snapshot 注册表，C 接宿主快照服务）
  - `StorePort`（Session/Run/Message/Citation/Feedback/Knowledge 仓库）
  - `RetrieverPort`（A 词法检索；C 混合向量 + 重排）
  - `ModelGateway`（A fixture/确定性生成器；C 批准模型）
  - `AuditPort`、`ClockPort`、`IdPort`、`KnowledgeAdminPort`
- **本地持久化用标准库 SQLite**，表与字段镜像未来 PostgreSQL（`assistant_sessions` / `messages` / `runs` / `dependencies` / `citations` / `feedback` / `knowledge_sources` / `versions` / `chunks` / `idempotency_records` / `outbox_events`），全部经 `StorePort`；C 换 PG repository 时业务代码不改。
- **共享知识层 `app/knowledge/`**：合成语料 + 来源/版本/分块元数据；`source_type`、`version`、`effective_from/to`、`scope`/ACL、`status`（`processing | pending_review | published | superseded | withdrawn`）、`submitted_by` / `reviewed_by`；检索只取 `published` 且当前有效、有权限的版本。A 提供最小导入/审核/发布 CLI 或 fixture 种子，**预留知识审核接缝**；C 换真实导入、独立审核与管理端 API。`agent-regulatory` 后续复用同一知识层，不另建语料。
- **问答管线**：QueryAnalyzer（确定性路由到 `product_faq | trade_rule_explanation | document_explanation | out_of_scope`）→ Retriever（先授权/发布/有效期过滤）→ EvidenceBuilder → Composer（A fixture/确定性；只允许引用证据包里的 ID）→ **代码 Reviewer**（引用存在、摘录匹配、金额/日期/规则号覆盖、Claim 支持关系、`support_level`）→ Publisher（重新授权、原子写答案/引用/审计）。
- **行为**：产品 FAQ、规则解释、当前快照/选区问答；缺规则版本/法域/适用日期时澄清；无证据时 `insufficient_evidence`；跨组请求 `needs_handoff`（automation / standards_audit / regulatory_advice）；**不修改正文、不审批、不扩大权限、不联网**。
- **前端**：`Knowledge Q&A` tab 从占位变成可用；会话绑定当前编辑器快照版本；问题/选区、Run 轮询与取消、Answer（outcome/support_level/claims/citations/limitations）、引用详情、反馈、旧版本提示与新建会话；`Fixture-backed` 明确标注；Automation / Legal 继续标 `not implemented`。
- **修改 `document-editor`**：assistant tabs 要求从“knowledge/automation/legal 都标 not implemented”改为“knowledge 可用，automation/legal 仍标 not implemented”。
- **A.1 Phase 1 合成语料扩展（本次追加，不新增能力）**：在既有 3 个 synthetic source 上扩充内容——贸易规则摘要 5→12 chunks（URDG/UCP/ISP98/ISBP 条款级摘要）、产品手册 5→12、内部政策 3→8，共 32 chunks；评测集 20→25 题。仍全部标注 `synthetic/演示用/非官方`，不引入真实 ICC 文本、真实银行资料、多来源权威等级或新的导入通道；`knowledge-assistant` 的合同、状态机与领域规则不变。
- **A.1 明确不做**：多来源权威等级/优先级（`authority_level`/`interpretation_of`）、真实 PDF/URL 导入、chunk 级语言、许可到期字段；这些留给后续 change，不混入 Phase 1。
- **A 明确不做**：PostgreSQL、真实 Worker/队列、真实身份/组织/ACL 接入、宿主快照/附件服务、真实模型与向量/重排、受控联网、语音/截图、管理端 UI、导出。它们都由 Port/Adapter 预留，不在 A 里冒充完成。

## Capabilities

### New Capabilities

- `knowledge-assistant`: 知识助手的 Session/Run/Message/Answer/Citation/Feedback 合同、异步状态机、授权与快照绑定、知识源发布/撤回与检索过滤、证据化回答与 Reviewer、澄清/弃答/转交、反馈与审计；当前用 local/fake Adapter 实现，生产 Adapter 可替换。

### Modified Capabilities

- `document-editor`: 右栏 assistant tabs 的能力标记改变——Knowledge Q&A 从 `not implemented` 变为可用；Automation / Legal 仍为未实现；不得渲染示例答案或伪造引用。

Phase 1 不新增 capability，也不修改 `knowledge-assistant` 的既有要求；它只扩充 `fixtures/knowledge/*` 与合成评测集，作为该 capability 的演示/验收证据。

## Impact

- **新增**：`app/assistant/`（api、schemas、application、domain、ports、adapters、persistence、worker）、`app/knowledge/`（来源/版本/分块/种子/最小发布 CLI）、`app/api/assistant.py`、`fixtures/assistant/*`、`fixtures/knowledge/*`、`web/src/components/KnowledgePanel.tsx`、`web/src/api/assistant.ts`、相关测试。
- **Phase 1 追加**：`fixtures/knowledge/*` 13→32 chunks；`fixtures/assistant/eval_questions.json` 20→25 题；`tests/test_assistant_eval.py` / `tests/test_knowledge_retriever.py` 的数量断言同步；`how_to_use.md` / `web/README.md` 的评测数字同步。无 schema、API 或依赖变化。
- **A.2 与 `knowledge-onboarding` 协作**：英文镜像语料、语言隔离与本地 fixture 补种会触及本 change 的 retrieval/seed 接缝；本 change 只记录底层任务与设计，不新增 durable spec，行为契约归 `knowledge-onboarding`。
- **修改**：`app/api/main.py`（挂载 `/assistant` router）、`app/config.py`（assistant 配置与 fake/生产模式校验）、`web/src/components/AssistantPanel.tsx`、`web/src/App.tsx`、`web/src/api/types.ts`、`web/src/styles.css`、`tests/`、`how_to_use.md` / `web/README.md`。
- **不改**：`app/state.py`（冻结的 `EditState`）、`AGENT_IDS`、现有 `parse/extract/normalize/audit` 链路与 `document-import`。
- **依赖**：新增 0 个 Python 包（SQLite 用标准库）；不引入向量库或模型 SDK。
- **升级路径（A → C）**：Fake Identity/Snapshot → 宿主 Adapter；SQLite repository → PostgreSQL repository；进程内执行器 → Worker/队列；词法检索 → 混合检索/重排；fixture Composer → 批准模型；fixture 知识语料/最小审核 → 知识导入/独立审核/管理端；最小面板 → 完整历史/引用/反馈/观测。领域规则、外部 DTO、状态机、Reviewer、权限判定与测试矩阵保持。
- **风险**：合成语料与 fixture 不能被当成法律结论；fake Adapter 必须在 production 失败关闭；选区偏移/跨用户隔离/撤权 redacted 必须从第一天在服务端执行；与 `agent-regulatory` 共享知识层需要约定所有权，避免两套语料。
- **预留的 C 升级计划**：通道表（K01–K15）、升级顺序、触发条件、待决策与反模式见 [`TBD-upgrade-to-c.md`](TBD-upgrade-to-c.md)；A 的 DTO/领域规则/Reviewer/权限判定在 C 中保持不变。