# Design

## Context

见 `proposal.md` 的 Why。当前实现事实：

- `KnowledgePanel` 已有 fixture 横幅、Session 绑定、问题输入、选区、Ask/Cancel；onboarding 文案和 chips 默认是中文。
- `QueryAnalyzer` 对 `What can you do?` / `How should I ask?` 返回 `out_of_scope`；对中文“你能做什么”有 `_HELP`，但只匹配中文。
- 知识层有 `KS-HELP-001`（zh-CN）与 3 个中文业务 source；没有英文业务语料。
- 本地 `runs/assistant.db` 仍可能是旧的 3 source/demo-1 数据库，没有帮助来源；`build_services` 只在空库时 seed，导致能力问题落到 `insufficient_evidence`。
- `agent-knowledge` 当前 28/28 complete 但尚未归档；本 change 作为独立 capability 规划，并联动其 design/tasks 记录 seed reconciliation 与语言隔离。

## Goals / Non-Goals

**Goals:**

- 首次打开知识 tab 默认英文 Can / Cannot / How，以及英文产品/规则快捷问题。
- 英文能力问题从英文帮助来源返回 `answered` + English Claim/Citation；中文问题继续使用中文来源。
- 为现有 synthetic 语料增加英文镜像，使英文产品/规则事实问题可回答。
- 按语言隔离检索，避免中英来源混用与跨语言冲突。
- local/test 启动补种/升级 fixture 来源；帮助来源缺失时给出明确诊断。
- 不改变 Session/Run/Answer 合同、权限模型、outcome 枚举或 API 形状。

**Non-Goals:**

- 真实 ICC/SWIFT 原文或真实法律文本；英文语料仍是 synthetic、非官方。
- 服务端动态推荐、个性化 suggestions、埋点/A-B。
- 双语切换 UI、chunk 级语言、真实模型/向量/重排。
- 修改正文、审批、提交、联网、语音/截图或法律结论。
- 把 “你能修改文档吗” 从 handoff 改写成普通 help 回答。

## Decisions

### D1. 新 capability `knowledge-onboarding`，不修改既有 requirement

onboarding 与能力帮助是独立的产品行为：它依赖 `knowledge-assistant` 的 Answer 合同，但不改变该合同；也不改变 `document-editor` 的 tab 语义。把它作为新的 `knowledge-onboarding` capability，可以让 `agent-knowledge` 保持完成状态，避免为一个 UI/路由增量重写其 spec。

*替代方案：* 把 2A/2B 塞回 `agent-knowledge`。会把 28/28 重新打开，并让归档 spec 混入 onboarding。*替代方案：* 修改 `knowledge-assistant` requirement。需要先归档 `agent-knowledge`，且会把“帮助”与“问答核心”混在一起；本 change 不做。

### D2. 英文镜像语料 + 英文帮助来源，不新增 source type

为现有 4 个 synthetic source 增加英文镜像：

```text
Chinese (existing):  KS-PRODUCT-001 / KS-RULES-001 / KS-POLICY-001 / KS-HELP-001
English (new):       KS-PRODUCT-001-EN / KS-RULES-001-EN / KS-POLICY-001-EN / KS-HELP-002
chunks:              12 + 12 + 8 + 4 = 36 English, 36 Chinese
total:               8 sources / 72 chunks
```

`KS-HELP-002` 使用 `product_manual`、`public`、`language: en`、`synthetic: true`、`demo-1`，4 个 chunk 分别覆盖能做什么、不能做什么、怎么提问、怎么读回答。英文业务语料是中文 synthetic 摘要的英文镜像，不复制 ICC/SWIFT/银行原文；同样带 synthetic 声明。

使用既有 `product_manual` 而不是新增 `help_center` 类型，原因是 `source_type` 枚举与数据库字段已经稳定，新增类型没有行为收益；帮助内容本质上是产品使用说明。

*替代方案：* 只做英文 help、不做英文产品/规则语料。这样英文快捷问题只能问“你能做什么”，无法回答 `What documents...` / `What does URDG 758 article 20...`；不满足本次 scope。*替代方案：* 把英文文本硬编码在 Composer/前端。无法审核、版本化、撤回，也无法用统一 Answer 合同审计；不采用。

### D3. 英文快捷问题、只填充、不自动提交

无选区时提供 3 个英文问题：

```text
What can you do?
What documents are required for the application?
What does URDG 758 article 20 require for claims?
```

有选区时第一个替换为 `What does this passage mean?`。点击只执行 `setQuestion(prompt)` + focus，不调用 `createRun`。第一次回答后折叠为 `Show examples`，帮助卡片保留。

*为什么：* 自动提交会在用户只是浏览时创建 Run/Message，并污染评测与历史；填充后让用户可改问法。*替代方案：* 后端返回 suggestions。需要新 API/字段，A 阶段收益不足；C 再考虑。

文案放在组件旁的纯函数/配置里（`knowledgeSuggestions.ts`），默认英文，按 `selection` 返回，避免 JSX 内散落。文案必须与英文语料一致，不出现“summary whole document / edit clause / browse web”等未实现建议。

### D4. `_HELP` / `_HELP_EN` 路由 + 语言隔离，不新增 outcome

在 `QueryAnalyzer` 增加中文 `_HELP` 与英文 `_HELP_EN`，匹配 `你能做什么 / 怎么用助手 / 支持哪些问题` 以及 `What can you do? / How should I ask? / What questions can I ask?`；放在 `_EDIT`、`_AUDIT_ACTION`、`_REGULATORY` 之后，映射到既有 `product_faq` 并设置 `capability_help=true`。帮助回答仍是 `answered` + Claim + Citation + limitations，Reviewer 不变。

按 `QueryPlan.language` 选择帮助来源：中文→`KS-HELP-001`，英文→`KS-HELP-002`。检索时：

- 先按 `language` 过滤 `published_chunks`，中文问题只看到中文 source，英文问题只看到英文 source；
- `capability_help` run 再按 `help_source_id` 限定到对应帮助来源；
- 普通产品/规则/文档 run 排除帮助来源，避免“提交/审批/文档/问题”等通用词污染引用。

“你能修改文档吗”保持现有 `needs_handoff`：帮助卡片已经明确 Cannot；如果把带“修改”的能力问题改写成 help，容易吞掉真实改稿请求。

*替代方案：* 新增 `capability_help` intent。需要改 `Intent` 类型、Composer 分支与测试；A 阶段用 `product_faq` + 明确帮助 chunk 足够，且能复用现有评测。若未来 help 语料变大、路由冲突，再升级为独立 intent。

### D5. 帮助来源走同一套治理与评测

中文/英文帮助来源都必须经 `pending_review → published`，`reviewed_by != submitted_by`；只检索 `published` 且当前有效、语言匹配的版本。撤回后默认检索消失，历史消息按既有 `redacted` 规则处理。

评测新增英文 Q29–Q33（能力/不能/怎么问、产品材料、URDG 20），总数 28→33；来源 4→8、chunk 36→72。不降低 `outcome_accuracy >= 0.95`、`citation_hit_rate >= 0.9`；英文题要求 `language=en`、citation 来自英文 source。

*为什么：* 帮助文本也是知识，不能被模型记忆或系统提示词替代；否则“能做什么”会随实现漂移且无法审计。

### D6. 文案与帮助语料允许 A 阶段少量重复

UI 卡片与中英文帮助来源共享同一组事实，但一个在 TS 文案、两个在知识 fixture；A 阶段接受重复，用测试锁定关键边界（不能修改/不联网/不审批/只解释已发布来源）。C 阶段再考虑由同一份内容生成两端，或服务端返回 onboarding payload。

*替代方案：* 现在就加 `GET /assistant/onboarding`。会引入新的 API 合同、加载状态与失败态；A 阶段不值得。

### D7. 英文答案模板必须与 `plan.language` 一致

`FixtureComposer` 目前使用中文 Claim/limitation/handoff 文案。英文问题必须使用英文模板：`According to ...`、英文 synthetic/trade/document limitations、英文 handoff 说明；`QueryAnalyzer` 的澄清问题也要按语言输出。否则英文问题会出现 `language=en` 但正文中文的混合结果。

英文产品/规则事实问题仍引用英文镜像语料；文档选区问题引用快照原文（可能是中文），但 Claim 模板与 limitation 使用英文。

### D8. 本地 fixture 补种/诊断，不让旧库伪装成“没有知识”

当前 `build_services` 只在 `knowledge_count()==0` 时 seed；旧库永远不会得到新 source/version，导致 `What can you do?` 落到 `insufficient_evidence`。

- local/test 启动时补种缺失 fixture source、升级 fixture version；已存在且相同的 source/version 不重复发布；
- 如果补种失败，启动 MUST 以明确错误失败；
- 如果运行期对应帮助来源仍缺失，返回 `HELP_SOURCE_UNAVAILABLE`（Run failed）或等价明确诊断，不得返回 `insufficient_evidence`；
- 生产模式不做 fixture 补种，仍按 fake/生产校验失败关闭。

*替代方案：* 只在文档里让用户删库。用户实测已经踩到，单靠文档不足；需要启动补种/诊断。

## Risks / Trade-offs

- **[英文翻译与中文语料漂移]** → 英文镜像是 synthetic 摘要，逐 chunk 对齐中文版本；评测覆盖英文 product/rule/help；版本化/审核。
- **[语言过滤导致跨语言召回下降]** → A 只承诺同语言问答；中文问题只看中文、英文只看英文；跨语言检索留给 C。
- **[快捷问题变成死问题]** → 固定 3 条并加入“英文建议问题可回答”测试；语料变化时先改测试/期望，再改文案。
- **[help source 抢走普通产品问题]** → 帮助来源只用于 `capability_help` run；普通问题按语言过滤并排除 help source；评测检查 citation 来源。
- **[“你能修改文档吗”语义模糊]** → 保持 handoff；帮助卡片负责说明“不能修改”，不把该问题纳入 `_HELP`/`_HELP_EN`。
- **[旧库缺 help source 被当成知识不足]** → local/test 启动补种/升级；运行期缺来源返回 `HELP_SOURCE_UNAVAILABLE`；文档说明删库/重启。
- **[补种重复发布/覆盖用户数据]** → 只补缺失 source/version，已发布相同版本跳过；生产模式不补种。
- **[UI 与 help 语料重复导致不一致]** → A 接受；P1 用共享文案表/关键句测试收敛，C 再做单一来源。
- **[归档顺序]** → `agent-knowledge` 先归档，再归档本 change，避免 `knowledge-assistant` durable spec 与 onboarding capability 的顺序歧义。

## Migration Plan

1. 增加 4 个英文 source（product/rules/policy/help），中文 4 + 英文 4 = 8 sources / 72 chunks；英文 help 为 `KS-HELP-002`。
2. 更新 `build_services`/`seed_knowledge`：local/test 启动补种缺失 source、升级 fixture version；旧 3-source DB 重启后应变为 8/72。
3. 增加 `_HELP_EN`、英文产品关键词、语言过滤、help source 映射；增加英文 Composer/澄清模板。
4. 增加 Q29–Q33，跑 `scripts/assistant_eval.py` 与全量 pytest。
5. 将 `KnowledgePanel` 默认文案/chips 改为英文，补组件测试与浏览器 e2e。
6. 更新 `how_to_use.md` / `web/README.md` 的英文提示词、8/72/33 数字与旧库处理。

回滚：移除英文 sources/help、`_HELP_EN` 与语言过滤、英文 chips；无 schema 迁移。旧中文库仍可按原逻辑运行，历史英文消息会因来源不存在而 redacted。

## Open Questions

1. **英文语料的所有权与翻译质量** —— 本 change 用 synthetic 镜像；真实英文语料需要业务/法律审核，不能由本 change 冒充。
2. **UI locale 切换** —— 本 change 默认英文；是否增加中英切换 UI 留给后续，不阻塞英文默认路径。
3. **服务端 suggestions** —— P1/C 再决定是否按语料/会话动态生成；当前静态 3 条已满足首屏引导。
4. **“你能修改文档吗”的友好回答** —— 当前保持 handoff；若需要更直接的自然语言拒绝，后续再加精确分支，不影响真实改稿请求。