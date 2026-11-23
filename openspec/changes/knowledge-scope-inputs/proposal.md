# Proposal

## Why

页面只有一个问题框，用户无法声明"我关心哪个法域、哪一天、哪条规则"。而实测显示这层声明影响很大：同一个问题加不同法域过滤，结果完全不同 —— 海关估价类问题在 `WTO` 下命中《估价协定》第七条、在 `EU` 下命中 UCC 第 74 条、在 `CN` 下则 `confidence=low` 无可用命中。

同时，法规证据腿只在问题里出现 `guarantee / clause / rule / URDG / UCP / standby / 保函 / 条款` 时才启动（`STATUTE_INTENTS = {trade_rule_explanation}`），而语料真正覆盖得好的那类问题（海关估价、申报内容、原产地）多被判成 `product_faq` 或 `out_of_scope` —— 于是页面上几乎看不到法规引用。

关键事实：**后端契约与前端请求层其实早已支持这三个字段**（`RunCreate.jurisdiction_codes / applicable_on / rule_version`，`createRun` 也会发送），缺的只是页面控件与"显式范围"的路由语义。

## What Changes

- **S1 · 页面范围输入**：问答面板新增 `Scope (optional)` 一行 —— 法域单选、交易日、规则；空值一律**不发送**（服务端 `Strict(extra="forbid")`，多发/发错字段会 422）。
- **S1b · 法域选项取自语料**：能力自检响应新增 `statute.jurisdictions`，来自法规服务的语料文档列表（30 秒缓存）；未测量时为 `null`，**不假装空列表**。
- **S1c · 规则只用于适用性**：`rule_version` 用于消除"哪一版适用"的澄清打断，并写入回答的限制说明；明确它**不收窄**法规检索（法规服务的过滤项里没有规则名）。
- **S2 · 显式范围补强意图（A'）**：用户显式声明了范围时，视作"在问法规" —— 除明确转交类请求外，不再受 `STATUTE_INTENTS` 限制而尝试法规证据腿。
- **S2b · 路由顺序**：`out_of_scope` 且显式声明范围时，先走标准检索（法规腿优先），再决定是否联网；**未声明范围时保持"直接联网"的现状**。
- **S2c · 回退衔接**：显式范围下 `out_of_scope` 的"法规不可用 → 联网"沿用既有回退，且只在用户开启联网时发生。

**不变量（本 change 必须保持）**：未声明范围时行为与今天一致；法规不可用仍回落本地语料；"没检查"永不被呈现为"没有相关规定"；界面文案全英文。

**Out of scope**：多法域同时选择（API 支持，但面板窄，留待后续）；把规则名作为第二路检索串；法域/日期在会话间持久化；People/组织级默认范围。

## Capabilities

### New Capabilities

- `knowledge-scope`: 提问时声明的检索范围如何被校验与传递、如何用于法规检索过滤、法域选项如何反映语料实际覆盖，以及"显式范围"如何补强意图判定与回退顺序。

### Modified Capabilities

<!-- 无：`statute-retrieval` 仍属 knowledge-statute-retrieval（尚未 archive），本 change 只增加范围输入与意图补强，不改变其既有需求语义。 -->

## Impact

- **前端**：`web/src/components/KnowledgePanel.tsx`（范围控件 + 载荷）、`web/src/api/assistantTypes.ts`（`Capabilities.statute.jurisdictions`）、组件测试与 `web/e2e/*`。
- **后端**：`app/assistant/schemas.py`（`StatuteCapability.jurisdictions`，增量）、`app/assistant/service.py`（能力填充、`should_try_statute`、`_general_route` 与 `_should_fallback` 的顺序）、`app/assistant/statute.py`（语料法域列表 + 缓存）。
- **外部系统**：法规服务 `/v1/corpus/documents`（新增一次调用，30 秒缓存；无 token 时应回退为"未测量"）。
- **依赖**：无新增 Python 包。
- **测试**：新增范围载荷与路由顺序的组件/服务测试；`out_of_scope + 显式范围` 必须有集成用例。
- **观测**：运行记录里保留 `jurisdiction_codes / applicable_on / rule_version` 的实际取值，并说明范围是否参与意图补强。