# Proposal

## Why

用户勾选 “Search the web for the latest” 后，系统可能完全不搜，而界面没有一句话解释。实际运行记录显示：`processor: fixture`、`retrieval: [{layer:"web", status:"skipped", detail:"web_unavailable"}]`——后端既没有配置模型，也没有自建 web provider；而面板只渲染 `blocked / failed / ok`，`skipped` 是静默的。再加上通用联网还依赖 `PROCESSOR_APPROVED`、`GENERAL_WEB` 与“问题必须范围外”三道隐形条件，用户只能靠猜。

此外，路由用 `isinstance(self.gateway, DoubaoGateway)` 判断“能否使用搜索工具”，把具体实现类硬编码进业务逻辑：fixture/替身网关永远无法演示这条通道，测试也只能靠真实类构造。

本 change 只做两件事：让**服务端能力可被发现**，让**每一次回答都自解释**（用了哪条路、联网为什么没发生）。不做配置收敛，也不改变任何检索策略。

## What Changes

- **能力探测端点**：新增 `GET /assistant/capabilities`，返回模型是否配置、处理器是否已批准、三条证据层（local / approved_web / general_web）是否可用、出站策略版本与准入域名数量；**不返回任何密钥**。
- **网关能力标志**：网关声明 `supports_tool_search`，通用通道的路由改为读取该标志，不再依赖具体类；fixture/替身网关可显式声明不支持。
- **回答自解释**：`Answer` 增加 `route`（`published | document | general_web | handoff | none`）与 `web` 摘要（`requested / status / reason / hint`），由服务端在生成答案时写入；旧记录缺字段时按 `null` 兼容。
- **面板状态**：启动时读取能力；没有外部能力时开关置灰并给出原因；有通用通道时改写开关文案；`skipped` 也显示 notice；in-scope 问题显式提示 “answered from published sources · web not needed”；原因码映射为人话提示。
- **测试与文档**：能力端点契约测试、路由标志测试、三种 `route` 的答案测试、UI 状态测试；README 增加“为什么没联网”的排查表。

**不做**：W3 的配置收敛与 `assistant_doctor.py`；W4 的“in-scope 问题也可联网”；任何检索、闸门或来源权威性的变化。

## Capabilities

### New Capabilities

- `assistant-capabilities`: 定义知识助手对外暴露的部署能力视图（模型/处理器/证据层/出站策略）以及“是否支持只读搜索工具”的网关标志，供前端决定开关是否可用。
- `assistant-answer-provenance`: 定义每条回答的路径与联网摘要（`route` / `web.requested/status/reason/hint`），以及界面在“能力缺失、被跳过、被拦截、无需联网”四种情形下的可见表达。

### Modified Capabilities

<!-- 无。assistant-model-gateway / knowledge-retrieval-layers 所在 change 尚未归档；本 change 以新能力承载可观测性，不改其行为要求。 -->

## Impact

- **后端**：`app/api/assistant.py`（新增端点）、`app/assistant/schemas.py`（`Capabilities`、`WebSummary`、`Answer.route/web`）、`app/assistant/gateway.py`（`supports_tool_search`）、`app/assistant/service.py`（路由改用标志；写入 route/web）、`app/assistant/settings.py`（只读地暴露能力所需的布尔值）。
- **前端**：`web/src/api/assistant.ts` / `assistantTypes.ts`（能力与摘要类型）、`web/src/components/KnowledgePanel.tsx`（能力驱动的开关与提示）、`web/src/styles.css`。
- **测试/文档**：新增能力端点与 route/web 用例；面板状态用例；`web/README.md`、`how_to_use.md` 增加“为什么没联网”排查表。
- **风险**：能力端点可能泄露部署细节（只返回布尔与版本，不含密钥/URL）；`Answer` 字段为可选，旧消息仍可反序列化；路由改用标志后必须保证未声明标志的实现默认“不支持”，保持 fail-closed。