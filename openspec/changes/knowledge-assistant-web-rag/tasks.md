# Tasks

## 1. 契约、配置与审计骨架

- [x] 1.1 在 `app/assistant/schemas.py` 增加 `RunCreate.web_search: bool = False` 与 `RunStage` 的 `screening` / `local_retrieval` / `web_search`，并确认 `extra="forbid"` 对未知字段仍然拒绝；验证：新增契约用例覆盖默认值、显式开启与未知字段拒绝，`tests/` 相关套件通过。
- [x] 1.2 增加模型与联网的配置解析（`SMART_EDIT_ASSISTANT_MODEL=doubao:<model>`、`SMART_EDIT_ASSISTANT_WEB=off|fixture|http`、`SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED=1`），未配置时保持现状；把 `assert_safe_mode` 改为按已批准 provider 白名单放行；验证：新增配置用例覆盖未配置、非法值、白名单内外、`approved_processor` 标记与 production 启动行为。
- [x] 1.3 在 `pyproject.toml` 加入运行时 `httpx`，并新增审计事件常量与脱敏辅助（理由码、`sha256` 前缀、禁止字段过滤器）；验证：`pip install -e .` 后相关单测通过，审计载荷断言不含正文与实体值。

## 2. 出站闸门（egress policy）

- [x] 2.1 新增 `EgressPolicyPort` 与规则实现：选中文本重叠、金额/编号/账号、`{{variable}}`、超长粘贴、身份字段、非准入域名参数分别给出 `allow | redact | deny` 与理由码；验证：表驱动单测覆盖每类规则与边界（空问题、超长、混合实体）。
- [x] 2.2 实现失败关闭与策略版本：配置缺失/损坏/判定超时时返回 `deny`，并在运行记录中保存 `policy_version`；验证：新增用例模拟异常与超时，断言不产生任何外呼且错误可解释。
- [x] 2.3 把闸门接入 `execute_run`：`analyze` 之后、任何外呼之前进入 `screening` 阶段；allow/redact 才继续，deny 直接结束并写入 `egress_blocked`，allow/redact 写入 `egress_allowed`；联网轮次的消息以 `visibility="redacted"` 保存实际外发查询；验证：新增服务层用例断言阶段、审计事件与消息存储形态。
- [x] 2.4 前端接入出站预览：开关默认关闭、显示“Will send / Will not send”、拦截时展示原因；验证：`KnowledgePanel` 单测覆盖默认关闭、开启预览与拦截提示，且不影响既有 `Knowledge question` / `Ask` 断言。

## 3. 本地第二层与联网层

- [x] 3.1 新增 `RagPort` 并以适配器包装现有 `LexicalRetriever`（保留 published/effective/scope 过滤与语言隔离）；验证：契约测试断言返回 `EvidenceCandidate` 形状、语言隔离与失败时的显式错误。
- [x] 3.2 新增 `WebSearchPort` 与 fixture provider，覆盖命中、域名越界、超时、重复 URL、含指令注入的页面；把结果转换为 `approved_web` 候选（`locator{url, domain, retrieved_at, provider, rank}`、`source_text` 片段、`sha1(url|content_hash|chunk)` 引用 ID）；验证：新增单测逐项断言候选字段、越界丢弃与注入内容不改变权限。
- [x] 3.3 实现分层执行：`local_retrieval` 与 `web_search` 在闸门后并行，各自独立超时与失败标记；合并去重（同 URL 保留最高分）并写入 `web_evidence_dropped` 审计；验证：新增合并/去重/超时用例，断言降级文案与审计事件。
- [x] 3.4 实现等级与冲突策略：联网证据参与时 `support_level` 上限 `qualified`；规则版本/生效日/适用范围不得由联网证据支撑；本地与联网冲突保留并降级；验证：新增“web-only 不得 strong”“本地 vs 网页冲突保留”“仅 web 且缺规则信息 → unable_to_assess”用例。
- [x] 3.5 提供 HTTP 适配器骨架（联网 provider、内部 RAG 服务），使用 `httpx` 与可注入传输；验证：用 `httpx.MockTransport` 的契约测试覆盖 URL 形状、鉴权头缺失、非 200、超时映射，不发起真实网络请求。

## 4. 模型网关（豆包 / Ark）

- [x] 4.1 实现 `DoubaoGateway`（OpenAI 兼容 `/chat/completions`，`httpx`，JSON 输出 + Pydantic 校验，记录 provider/model/task/耗时）；验证：`httpx.MockTransport` 契约测试覆盖合法响应、字段缺失、枚举越界、非法 citation id → 各自正确失败。
- [x] 4.2 接入未配置/凭据无效/超时的失败语义：不得回退其他 provider，不得发布部分结果；验证：新增用例断言 `MODEL_OUTPUT_INVALID` / `MODEL_TIMEOUT` / `PROVIDER_NOT_CONFIGURED` 三种结束方式。
- [x] 4.3 用网关替换 `FixtureComposer` 的调用位置但保留 fixture 默认：配置存在且通过出站判定时用于 composing（查询分析可继续用规则），复核 `review_answer` 与冲突检测 MUST 仍执行；未登记为 `approved_processor` 的提供方 MUST 被拒绝且不得静默改用 fixture；验证：新增用例断言批准/未批准两种外呼结果与复核始终执行。
- [x] 4.4 注入与越权测试：网页证据中含“忽略之前指令”等内容时，模型请求不含工具、不含内部 URL、不触发新检索；验证：新增用例断言请求体字段白名单与被拒行为。

## 5. 前端透明度与文档

- [x] 5.1 扩展 `web/src/api/assistantTypes.ts` / `assistant.ts`：`web_search` 入参、文章来源标签（`approved_web`）、`locator` 字段与层状态；验证：类型检查通过，新增 API 单测覆盖请求体与响应解析。
- [x] 5.2 `KnowledgePanel` 增加来源分区（Published / Web / Document）、网页条目（域名 · 抓取时间 · Unverified third-party）、层失败说明、脱敏历史提示，以及“由哪个处理方生成”的标注；验证：新增单测覆盖分区渲染、失败说明、处理方标注与“不得声称已联网核实”的文案约束。
- [x] 5.3 e2e：默认关闭时监听网络并断言无外部检索请求；开启后断言来源分区与抓取时间可见；构造拦截场景断言提示可见；验证：`web/e2e/knowledge.spec.ts` 或新 spec 在 desktop 项目通过。
- [x] 5.4 更新 `web/README.md` 与 `how_to_use.md`：开关语义、出站清单、来源分区、拦截原因、默认值与回滚方式；验证：文档可 grep 到 `web_search`、`egress`、`approved_web`，且命令与实际脚本一致。

## 6. 集成验证

- [x] 6.1 运行后端与前端全量校验（`pytest`、`npm --prefix web run verify`）并修复回归；验证：两条命令均以 0 退出，无失败用例。
- [ ] 6.2 手动走查四条路径并记录结果：默认关闭、开启后正常作答、闸门拦截、联网/第二层失败降级；验证：四份简短记录（截图或日志摘要）附在 PR 描述中，确认无“已联网核实”的错误表述。

## Workflow follow-up

- 归档本 change 前确认 `agent-knowledge` 的 `knowledge-assistant` 归档顺序，避免能力名冲突。
- 与法务/安全确认外发范围、allowed domains 与 provider 条款后，再在生产开启 `SMART_EDIT_ASSISTANT_WEB=http`。