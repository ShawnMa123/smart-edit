# Proposal

## Why

知识助手已经能返回带引用的答案，但首次使用仍有两个问题：

1. 面板的 onboarding 文案和快捷问题默认是中文，与英文 UI 不一致；实测输入 `What can you do?` 仍是 `out_of_scope`。
2. 本地旧的 `runs/assistant.db` 只有 3 个旧 source，没有 `KS-HELP-001`；能力问题被限定在帮助来源检索，于是返回 `Answer · insufficient_evidence`，把“fixture 未补种”伪装成“没有知识”。

本 change 把首次使用引导升级为 **英文优先、端到端可回答**：英文 onboarding、英文快捷问题、英文产品/规则/政策/帮助语料、英文答案模板；同时让 local/test 启动补种/升级 fixture 来源，并在帮助来源缺失时给出明确诊断。它不改变 Session/Run/Answer 合同、权限模型或现有中文语料。

## What Changes

- **2A 英文 onboarding**：`KnowledgePanel` 默认英文文案（Can / Cannot / How），英文快捷问题：
  - `What can you do?`
  - `What documents are required for the application?`
  - `What does URDG 758 article 20 require for claims?`
  - 有选区时替换为 `What does this passage mean?`；点击只填入并聚焦，不自动运行；第一次回答后折叠为 `Show examples`。
- **2B 英文语料与路由**：
  - 为现有 synthetic 语料增加英文镜像：product 12、trade rules 12、internal policy 8、help guide 4；总计 **8 个 source / 72 chunks**（中文 36 + 英文 36）。
  - 新增 `KS-HELP-002`（`product_manual`、`public`、`language: en`、`synthetic`、`demo-1`，4 chunks）。
  - 新增 `_HELP_EN` 与英文产品关键词路由；英文能力问题从 `KS-HELP-002` 返回 `answered` + English claim/citation。
  - 按语言隔离检索：英文问题只引用英文来源，中文问题只引用中文来源；MUST NOT 在同一答案中混用。
  - `FixtureComposer` 增加英文 Claim/limitation/handoff/clarification 文案，避免“英文问题 + 中文正文”。
- **2C 本地库补种/诊断**：
  - local/test 启动检测已有 DB，补种缺失 fixture source、升级 fixture version；旧 3-source 库重启后应能回答问题。
  - 若帮助来源仍缺失，返回明确的 `HELP_SOURCE_UNAVAILABLE`（Run failed）或等价的“帮助指南未加载”诊断，MUST NOT 返回 `insufficient_evidence` 冒充知识不足。
- **评测与文档**：新增英文 Q29–Q33，评测 **28→33 题**；更新来源/chunk 数字、英文示例与旧库处理说明。
- **明确不做**：真实 ICC/SWIFT 原文、真实模型/向量/重排、服务端动态 suggestions、双语切换 UI、审批/改稿/联网能力；英文语料仍全部是 synthetic、非官方原文。

## Capabilities

### New Capabilities

- `knowledge-onboarding`: 英文首次使用引导、英文快捷问题、英文能力帮助、语言隔离检索，以及本地 fixture 补种/帮助来源缺失诊断。

### Modified Capabilities

<!-- 本次不修改既有 durable capability；knowledge-assistant 的核心合同保持不变，新增行为由 knowledge-onboarding 拥有。 -->

## Impact

- **前端**：`web/src/components/KnowledgePanel.tsx`、`knowledgeSuggestions.ts`、`styles.css`、组件测试、`web/e2e/knowledge.spec.ts`。
- **后端**：`app/assistant/domain/query.py`（英文 help/product 路由、英文澄清）、`app/knowledge/retriever.py`（语言隔离、help source 选择）、`app/assistant/pipeline.py`（英文 Answer/limitation 模板）、`app/assistant/bootstrap.py` / `app/knowledge/seed.py`（本地 fixture 补种）。
- **知识层**：新增 4 个英文 source（product/rules/policy/help），来源 4→8、chunk 36→72；`fixtures/assistant/eval_questions.json` 28→33 题。
- **文档**：`how_to_use.md`、`web/README.md` 更新英文提示词、8/72/33 数字与旧库处理。
- **依赖**：实现基于已完成的 `agent-knowledge` 代码；本 change 的规划也会更新 `agent-knowledge` 的 design/tasks，记录 seed reconciliation 与语言隔离（不新增 durable spec）。
- **风险**：英文翻译与中文语料漂移；语言过滤导致跨语言召回下降；旧库补种可能重复发布；帮助来源缺失仍被误判为 insufficient。对应设计见 `design.md`。