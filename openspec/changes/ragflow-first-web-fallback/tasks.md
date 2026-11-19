# Tasks

## 1. 判定语义：命中不再被丢弃（D2）

- [x] 1.1 `StatuteRetriever.judge()` 只要 `chunks` 非空就返回 candidates，`reason` 保留 `low_confidence` / `uncovered:*` / `superseded` / `degraded:keyword_only` 作为标注；同步修正 `StatuteOutcome.usable` 的语义注释。验证：`pytest tests/test_statute_retrieval.py -q` 中低置信、未覆盖、top score<0.6 三条用例断言 candidates 非空且 reason 不变
- [x] 1.2 `_annotate_statute()` 按新语义输出 caveat：`low_confidence` → "低置信，仅供参考"，`uncovered:*` → "该法域未被语料覆盖"，`superseded` → 保留既有提示；删除"未采用"措辞。验证：新增后端单测断言三种 reason 的 limitations 文案，且不再出现"未采用"
- [x] 1.3 更新离线回放断言：`tests/test_statute_replay.py` 的低置信样本改为断言"被采用 + caveat"，可用样本断言不变。验证：`pytest tests/test_statute_replay.py -q` 两条用例通过

## 2. RAG 优先（D1）

- [x] 2.1 `_should_try_statute()` 覆盖 `product_faq`，且产品意图把 RAG 命中与本地语料一起放进证据包（规则意图保持法规独占）。验证：单测断言产品问题触发 `search_detailed` 且最终 bundle 同时含 `statute` 与本地 source_type
- [x] 2.2 存在选区且 `intent == "document_explanation"` 时不调用法规服务，证据仍来自快照。验证：单测断言 statute 适配器零调用、引用为 `document_snapshot`
- [x] 2.3 规则意图在 RAG 有命中时不再调用本地检索（保持现有独占），记录一条 `retrieval` 日志含 `statute:hits`。验证：单测用计数检索器断言本地零调用；日志断言 `layers=statute:ok`

## 3. 联网回退只在 RAG 无文本时（D4）

- [x] 3.1 在服务层记录 `rag_has_text`（statute 层 `hits>0` 且有 candidates），新增自动回退判据：`rag_has_text == False` 且 `payload.web_search` 为真时，即使本地已有引用也调用一次 `_run_general_web()`。验证：单测断言"RAG 零命中 + 本地有引用"时 web 通道被调用 1 次；"RAG 有命中"时 0 次
- [x] 3.2 联网返回引用时以联网答案为主（`route="general_web"` + 未核验提示 + `GENERAL_WEB_FALLBACK` 说明）；联网无引用时保留本地答案，并在 limitations 写明"知识库与联网都未找到"。验证：两条单测分别断言 citations source_type、route 与 limitations
- [x] 3.3 自动回退同样过出站闸并写审计：策略缺失时不发请求、层为 `blocked`、回答说明原因；策略允许时审计出现 `egress_allowed`（含 `purpose`）。验证：`pytest tests/test_egress_policy.py tests/test_assistant_general_web.py -q` 新增/更新的用例通过

## 4. 合成提示词与来源标记（D3/D5）

- [x] 4.1 重写 `SYSTEM_PROMPT`：证据非空时不得返回 `insufficient_evidence`；证据只覆盖部分法域/概念时先说明边界再回答；保留"只引用给定 id、不编造"。验证：`pytest tests/test_assistant_gateway.py -q` 中新增断言 payload 同时包含"不得在证据非空时拒答"和"说明覆盖边界"两条约束
- [x] 4.2 `_route_for()` 保持由引用推导，并覆盖新语义：低置信法规被采用仍为 `statute`；联网答案为 `general_web`；仅本地为 `published`；无引用才是 `none`。验证：后端单测四条分支各一条断言
- [x] 4.3 真实模型验收提示词效果：对 `guarantee在wto定义是什么` 断言输出含引用、说明"仅覆盖中国司法解释"、且 `outcome != insufficient_evidence`。验证：一次真实模型 run 的 JSON 记录（无网络时可标记为待联调，不勾选）

## 5. 前端文案与默认态（D6）

- [x] 5.1 `statuteNotice()` 的 `low_confidence` 改为"低置信，仅供参考"；`uncovered` 保留；新增"RAG 未返回结果，已自动联网（未核验）"提示。验证：`web/src/components/KnowledgePanel.test.tsx` 新增/更新三条组件测试并通过
- [x] 5.2 联网开关默认态：首次渲染不再固定 `false`，拿到 capabilities 后按 `web.default_on` 同步；关闭时说明改为"关闭后本次不联网（仍会查 RAG 与本地语料）"。验证：组件测试断言默认勾选与关闭文案；`npm --prefix web run test` 通过
- [x] 5.3 `npm --prefix web run typecheck` 通过

## 6. 文档与验收

- [x] 6.1 更新 `how_to_use.md` 8.1/8.2 与 `README.md`：写明"RAG → 豆包总结 → 仅 RAG 无结果才联网"、`web.default_on` 语义、关闭联网的方法、以及低置信"仅供参考"文案。验证：按文档从零配置一次，启动日志 `statute=True`，并能复现一次"RAG 有结果不联网"
- [x] 6.2 手工验收四种结局并写入本 change 的 `acceptance-<date>.json`：①RAG 命中（含低置信）→ 有 `statute` 引用；②RAG 零结果 → 自动联网且 `route=general_web`；③联网关闭 → 不联网并说明；④两处皆空 → 明确"都未找到"且零引用。验证：四条记录均含 `route`、`retrieval`、审计字段，可回放

## 7. 回归

- [x] 7.1 全量回归：`.venv/bin/python -m pytest tests -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate ragflow-first-web-fallback --strict`。验证：四条命令均通过

## 8. 运行时错误修复（MODEL_OUTPUT_INVALID / 有证据仍拒答）

- [x] 8.1 `_normalise()` 修复 provider 把说明写进 `outcome`（或返回非法 `support_level` / `language`）的字段：`outcome` 非法但已给出 claims → `answered`，无 claims → `insufficient_evidence`；`support_level` 与 `language` 归一化。验证：`tests/test_assistant_gateway.py` 修复用例通过，缺字段仍重试两次后失败
- [x] 8.2 有证据时禁止裸拒答：`compose` 对 `insufficient_evidence` / `unable_to_assess` 且零引用做两次语义重试，仍拒绝则抛 `MODEL_REFUSED_EVIDENCE`；服务层改用 `EvidenceComposer` 逐条摘录证据、写 `model_refused_evidence` 审计。验证：gateway 重试用例 + 服务层兜底用例；真实模型 `guarantee在wto定义是什么` 端到端 `answered` / `route=statute` / 5 条法规引用

- [x] 8.3 `_canonical_citations()` 补齐 claim 引用但 `citations` 漏掉的条目（从证据包生成），避免模型少回一条 citation 就 `REVIEW_FAILED`。验证：新增单测断言 `validate_answer` 为空；真实 API `在wto里，什么是guarantee` → `succeeded` / `route=statute` / 5 条法规引用

## Workflow follow-up

- 评审通过后归档本 change（`/opsx-archive`）。
- 归档后确认主 spec 已包含 `knowledge-rag-first-fallback` 的 Purpose 与全部 scenarios。