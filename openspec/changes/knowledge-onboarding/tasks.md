# Tasks

## 1. 首次使用引导（2A）

- [x] 1.1 新增 onboarding 文案与快捷问题模块（`web/src/components/knowledgeSuggestions.ts` 或等价位置）：Can / Cannot / How 文案、无选区 3 条问题、有选区替换为“解释所选文本”，并在 `KnowledgePanel` 渲染可折叠卡片与 chips。Verify: 组件测试能查到 Can/Cannot/How、3 个按钮、fixture 横幅，且不出现示例答案/引用。
- [x] 1.2 实现 chips 交互：点击只填入问题并聚焦，不调用 `createRun`；第一次回答后折叠为 `Show examples`，可恢复；补齐中文/英文文案与可访问名称。Verify: `KnowledgePanel.test.tsx` 断言点击 chip 不触发 Run、折叠/恢复、选区变体；`npm --prefix web run typecheck` 通过。
- [x] 1.3 更新 `how_to_use.md` 与 `web/README.md` 的首次使用说明（卡片、chips、只填充不自动提交、未实现边界）。Verify: 文档描述与组件测试中的按钮/文案一致。
- [x] 1.4 英文 onboarding：把 `knowledgeSuggestions.ts` 的默认文案改为英文，chips 改为 `What can you do?` / `What documents are required for the application?` / `What does URDG 758 article 20 require for claims?`；有选区时用 `What does this passage mean?`。Verify: 组件测试断言英文 Can/Cannot/How、英文 chips、点击只填充不运行、折叠/恢复；`npm --prefix web run typecheck` 通过。

## 2. 帮助语料与路由（2B）

- [x] 2.1 新增 `fixtures/knowledge/help_guide.json`（`KS-HELP-001`、`product_manual`、`public`、`zh-CN`、`synthetic: true`、`demo-1`、4 chunks：能做什么/不能做什么/怎么提问/怎么读回答）；更新 seed 来源数与 chunk 数断言。Verify: 空库 seed 后 4 个 source、36 chunks 均为 `published`；help source 全部 synthetic；既有 32 chunks 内容不退化。
- [x] 2.2 在 `app/assistant/domain/query.py` 增加 `_HELP` 路由（放在 `_EDIT` / `_AUDIT_ACTION` / `_REGULATORY` 之后），覆盖“你能做什么 / 怎么用助手 / 支持哪些问题 / 可以问什么”；保持“你能修改文档吗”和“帮我改写”为 `needs_handoff`；能力帮助 run 只检索帮助来源，普通问题排除帮助来源。Verify: 纯路由单测覆盖 help 命中、真实改稿/审查/法规请求仍 handoff；help 问题不触发 `_EDIT`；普通问题不引用 `KS-HELP-001`。
- [x] 2.3 在 `fixtures/assistant/eval_questions.json` 增加 Q26–Q28（你能做什么 / 不能做什么 / 我该怎么提问），更新 `tests/test_assistant_eval.py`、`tests/test_knowledge_retriever.py` 的总数与来源断言。Verify: `scripts/assistant_eval.py` 输出 28 题；help 题均 `answered` 且 citation 来自 `KS-HELP-001`；`outcome_accuracy >= 0.95`、`citation_hit_rate >= 0.9`。
- [x] 2.4 更新 `how_to_use.md` / `web/README.md` 的帮助问答、语料规模 4/36、评测 28 题与示例问题。Verify: 文档数字与 `scripts/assistant_eval.py` 实际输出一致；`Fixture-backed` 声明仍在。
- [x] 2.5 英文语料镜像：为 product / trade rules / internal policy 增加 12+12+8 个英文 chunks，并新增 `KS-HELP-002`（product_manual、public、en、synthetic、demo-1）4 个 chunk；总来源 8、chunks 72。Verify: 空库 seed 后 8 个 source/72 chunks 均为 published；英文 source language=en；无真实 ICC/SWIFT 原文。
- [x] 2.6 英文路由与语言隔离：新增 `_HELP_EN`、英文产品关键词；按 `plan.language` 过滤来源，中文只检索中文、英文只检索英文；help source 按语言映射；`FixtureComposer` 与澄清文案按语言输出。Verify: 英文能力/产品/规则问题 cite 英文 source；中文问题 cite 中文 source；同一答案不混用语言。
- [x] 2.7 英文评测：新增 Q29–Q33（What can you do / What can't / How should I ask / product materials / URDG 20），总数 33；来源 8/72。Verify: `scripts/assistant_eval.py` 输出 33 题；英文题 `language=en` 且 citation 来自英文 source；阈值保持 `outcome_accuracy >= 0.95`、`citation_hit_rate >= 0.9`。
- [x] 2.8 本地 fixture 补种/诊断：`build_services`/`seed_knowledge` 对已有 DB 补种缺失 source、升级 fixture version；帮助来源缺失时返回 `HELP_SOURCE_UNAVAILABLE`，不得返回 `insufficient_evidence`。Verify: 旧 3-source DB 重启后变为 8/72；重复启动不重复发布；补种失败启动报明确错误。

## 3. 集成验收

- [x] 3.1 扩展 `web/e2e/knowledge.spec.ts`：打开知识 tab 看到引导卡片与 chips；点击 chip 只填充不自动运行；提交“你能做什么？”得到带 `KS-HELP-001` 引用的回答。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/knowledge.spec.ts --project=desktop` 通过。
- [x] 3.2 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`typecheck`、`build`；确认既有 audit/editor/knowledge 链路未变。Verify: 命令输出全绿，记录测试数量与评测数字。
- [x] 3.3 文档同步：`how_to_use.md` / `web/README.md` 更新英文提示词示例、8 sources / 72 chunks / 33 题、旧库补种/删库说明；保持 `Fixture-backed`。Verify: 文档数字与 `scripts/assistant_eval.py` 一致。
- [x] 3.4 英文集成验收：`knowledge.spec.ts` 验证英文 onboarding/chips、英文产品/规则回答、英文 help 引用、旧库补种后的 `What can you do?`；全量 pytest/vitest/typecheck/build 通过。Verify: Playwright + 回归命令全绿。

## Workflow follow-up

- 归档顺序：先归档 `agent-knowledge`（当前 28/28，但本次会追加 seed reconciliation/语言隔离任务），再归档 `knowledge-onboarding`，避免 `knowledge-assistant` durable spec 与本 capability 的顺序歧义。
- 本地 `runs/assistant.db` 应由 2.8 的启动补种自动升级；若补种失败，再删除重建或走 CLI `import → review`。
- 真实英文法律/ICC 语料、UI 中英切换、服务端动态 suggestions、chunk 级语言属于后续 change，不纳入本次完成标准。