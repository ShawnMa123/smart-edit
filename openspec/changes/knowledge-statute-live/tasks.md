# Tasks

## 1. 意图前置（D1）

- [x] 1.1 落地"选中词不劫持主题问题"：`document_explanation` 仅在问题指向片段或问题不含规则/产品主题词时成立；保留现有单测并补齐"指向片段"的正例（`请解释这段文字`、`Explain this passage`、`what does this clause mean?`）。验证：`pytest tests/test_assistant_pipeline.py -k "selected_word or intents_are_deterministic"` 通过
- [x] 1.2 端到端确认选中场景：选中 `guarantee` 提问 `什么是guarantee`，运行日志为 `intent=trade_rule_explanation`。验证：记录一次 run 的 `run plan` 日志行

## 2. 出站闸与审计（D2）

- [x] 2.1 `egress.py` 新增 `Purpose` 值 `statute` 与对应判定分支：要求策略已加载、复用脱敏与 40 字选中重叠拒绝、跳过域名白名单（内网服务/隧道）；不新增配置项。验证：单测覆盖 allow / redact / deny 三态
- [x] 2.2 `service.py:_run_local()` 在调用法规适配器**之前**过闸（输入为 `plan.question` + `payload.selection.selected_text` + `plan.entities`），把判定后的查询传给适配器；拒绝时不调用，层记 `status="blocked"`、`detail=<reason>`。验证：单测断言"拒绝时适配器零调用 + 层为 blocked"；允许时断言发给适配器的查询已脱敏
- [x] 2.3 审计：每次法规判定写 `egress_allowed` / `egress_blocked`，载荷含 `purpose="statute"`、`action`、`reason`、`policy_version`、`query_digest`，不含原文。验证：单测断言审计载荷字段与"无原文"
- [x] 2.4 文案：`_annotate_statute()` 增加 blocked 说明（"因出站策略未查询法规"），`KnowledgePanel.tsx:statuteNotice()` 增加 `blocked:*` 分支。验证：后端单测 + 组件测试各一条
- [x] 2.5 连带修改现有 `StubStatute` 用例：注入 `demo_policy()`，避免新闸 fail-closed 造成假回归。验证：`pytest tests/test_statute_retrieval.py tests/test_statute_recall.py` 全绿

## 3. 来源标记（D3）

- [x] 3.1 `schemas.Route` 增加 `"statute"`；`_route_for()` 依据 `answer.citations` 的 `source_type` 判定（法规引用 → `statute`；仅本地/网页 → 保持原值），不采用模型自述。验证：后端单测覆盖"法规答案"与"法规被拒后本地作答"两条
- [x] 3.2 前端：`AnswerRoute` 增加 `statute`；`KnowledgePanel` 中依赖 `route==='published'` 的"Answered from published sources"提示按新枚举处理，避免法规答案显示"web not needed"。验证：`npm --prefix web run test` 中相关组件测试通过
- [x] 3.3 运行详情自证：确认 `result.route` 与 `retrieval[statute].detail/hits` 同时可读。验证：一次手工 run 的 JSON 记录

## 4. 契约回放（D4）

- [x] 4.1 录制真实响应：对 `什么是guarantee`（法域按验收配置）调用一次 `/v1/retrieve`，把原始响应保存为 `fixtures/assistant/mercatoria_guarantee.json`；`text` 截断到 excerpt 长度并注明来源与用途。验证：fixture 可被 `json.load` 且含 `chunks/diagnostics/field_matches/corpus`
- [x] 4.2 新增 `tests/test_statute_replay.py`：用 `httpx.MockTransport` 注入 `StatuteRetriever`，跑完整 run，断言 ①请求体 `queries` 含扩展词、`filters` 与 payload 一致 ②判定与录制一致 ③引用 `locator` 含 `doc_id/article_label/jurisdiction/effective_from` ④层记录与 `route` 一致。验证：离线（无网络/隧道）`pytest tests/test_statute_replay.py` 通过
- [x] 4.3 覆盖两条分支：若首份录制为"可用"，再补一份"低置信"样本；若首份为"低置信"，补一份"可用"样本，分别断言"引用法规"与"法规被拒 + 本地兜底 + 说明"。验证：两条用例各自断言 outcome/route/limitations

## 5. 启用与校准（D5 / D6）

- [x] 5.1 文档：`how_to_use.md` 增加启用步骤（`SMART_EDIT_STATUTE`、`MERCATORIA_BASE_URL`、`MERCATORIA_API_TOKEN`、隧道）、验收命令与回滚方式（清空变量回到词法-only）。验证：按文档从零配置一次，启动日志为 `statute=True`
- [x] 5.2 校准网格：跑 `{原句 / +定义词 / +定义词+URDG} × {带法域 / 不带法域}` 六格，记录 `confidence`、top chunk（`doc_id/article_label`）、`score`、`requested_uncovered`，写入 `design.md` 的 Findings。**本任务不改代码**。验证：六格数据齐全，结论明确"带法域是否可行"

## 6. 回归与验收

- [x] 6.1 全量回归：`.venv/bin/python -m pytest tests -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate knowledge-statute-live --strict`。验证：四条命令均通过
- [x] 6.2 手工验收（两种结局各一次）：①法规可用 → 引用 `source_type="statute"`、`route="statute"`；②法规被拒 → 本地定义 + "命中 N 条但置信度低"说明、`route="published"`；两次都记录 `retrieval`、审计与 `route`。验证：运行记录可回放