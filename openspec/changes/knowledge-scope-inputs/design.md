# Design

## Context

动机见 `proposal.md`。塑造本设计的既有事实（均在本仓库核实）：

- **契约与请求层已就绪**：`RunCreate` 已有 `jurisdiction_codes: list[str]`（≤20）、`applicable_on: str`（≤20）、`rule_version: str`（≤120），且 `Strict(extra="forbid")`；`AssistantService` 已把前两者传给 `analyze(...)` 与 `_retrieve_layers(..., payload.applicable_on)`；`web/src/api/assistant.ts` 的 `createRun` 已会把这三个字段（非空时）写进请求体。缺的只有 `KnowledgePanel` 的控件。
- **法规过滤已映射**：`app/assistant/statute.py::build_filters` 把 `plan.jurisdictions` → `filters.jurisdictions`、`applicable_on` → `filters.as_of`（不传就不过滤，绝不用"今天"顶替交易日）。
- **意图门是当前瓶颈**：`service.py` 的 `STATUTE_INTENTS = {"trade_rule_explanation"}`；实测同一批问题：`What rules apply to the customs value of imported goods?` → `product_faq`、`What are the rules on the origin of goods?` → `out_of_scope`、`What does URDG 758 article 20 require for claims?` → `trade_rule_explanation`。前者才是语料覆盖好的那类。
- **过滤确实有效**：同一问题实测 `WTO` → 《估价协定》第七条、`EU` → UCC 第 74 条、`CN` → `confidence=low` 无可用命中。
- **路由现状**：`_general_route(plan, payload)` 在 `out_of_scope + web_search + general 可用` 时直接走联网（优先于 `_standard_answer`）；`_should_fallback(...)` 只覆盖 `trade_rule_explanation / product_faq / document_explanation`。
- **法规服务没有规则名过滤**：`filters` 仅支持 `jurisdictions / applies_to / as_of / doc_ids / article_ids`；法域清单只能从 `/v1/corpus/documents` 的 `jurisdictions` 取得（`/health` 不含）。

## Goals / Non-Goals

**Goals:**

- 页面可声明范围，且声明后**确实改变**法规检索结果（可演示：`WTO` + 海关估价问题 → 估价协定）。
- 显式声明范围时，法规证据优先于"直接联网"，但仍受用户联网开关约束。
- 未声明范围时，行为与今天**逐字节一致**（天然灰度，无需开关）。
- 界面不承诺做不到的事（规则版本不收窄语料；法域清单来自实测）。

**Non-Goals:**

- 多法域同时选择（API 支持 ≤20，但面板窄；留待后续）。
- 把规则名作为第二路检索串去影响排序。
- 范围在会话间持久化，或组织级默认范围。
- 改变 `statute-retrieval` 既有的可用性判定与降级语义。

## Decisions

### D1 · 控件形态：常驻一行 + 法域单选 + 日期 + 规则

一行 `Scope (optional)`：`Jurisdiction`（单选）、`As of (trade date)`（date）、`Rule (applicability only)`（文本）。默认全空＝沿用现状。

- 备选：折叠 `Filters ▸` —— 否决：演示时光靠点开才看见，等于白做。
- 备选：法域多选 chips —— 否决：352px 面板宽会被七个 chip 挤成两行；API 支持不等于现在要做。
- 备选：逗号文本框 —— 否决：大小写与拼写错误无法在服务端纠正，会把 422 变成"看起来没效果"。

### D2 · 载荷映射与省略规则

| 控件 | 值 | 请求体 |
|---|---|---|
| Jurisdiction | `Any covered jurisdiction` | 省略 `jurisdiction_codes` |
| | `EU` | `jurisdiction_codes: ["EU"]` |
| As of | `2026-03-01` | `applicable_on: "2026-03-01"` |
| | 空 | 省略 |
| Rule | `URDG 758` | `rule_version: "URDG 758"` |
| | 空 | 省略 |

- 字段名必须是 `jurisdiction_codes`（不是 `jurisdictions`）；写错会因 `extra="forbid"` 直接 422。
- 空值**省略**而不是发 `null`／`[]`：`applicable_on`/`rule_version` 为 `None` 时 pydantic 可接受，但省略能让"未声明"与"声明为空"在请求日志里可区分。
- 日期用 `<input type="date">`，天然 ISO，避免喂出非法 `as_of`。
- 规则文本 `maxLength=120`，与 schema 一致；超长时禁用提交，不截断。

### D3 · 法域选项来自实测；测不到就说测不到

`Capabilities.statute` 新增 `jurisdictions: list[str] | None`：
- 有法规源时，从 `/v1/corpus/documents?limit=1` 取 `jurisdictions`，与 `health()` 共用 30 秒缓存（同一次探测、同一次失败语义）。
- 未配置法规源 → `null`；请求失败 → `null`（不是 `[]`）。
- 前端：`null` 时单选禁用并显示 `Jurisdiction catalogue not measured`，同时说明"无法按法域收窄"；**不得**回退到硬编码 7 个法域（那会暗示覆盖，违反 spec）。

- 备选：前端常量清单 —— 否决：语料变了会漂移，且会把未覆盖法域列成可选。
- 备选：每次提问现查 —— 否决：面板每次交互多一次跨服务调用。

### D4 · 规则版本只做适用性

仅用于 `analyze(rule_version=...)`：当问题涉及"是否适用"时，有值即不再追问版本。**不**写入 `filters`（服务不支持），**不**在回答里声称检索已被收窄。回答里也不新增 limitation —— 少一次契约变动，也避免与既有 `support_level` 语义纠缠。

- 备选：把它拼进 `queries` 作为第二路检索串 —— 否决：语料里通常没有该规则，反而会引入噪声；且改变检索行为却没有可解释的验收。
- 备选：在 limitations 里写"已按 URDG 758 判定适用性" —— 暂缓：需要 Answer 语义评审，放到后续 change。

### D5 · A'：显式范围补强意图

```python
scope_declared = bool(payload.jurisdiction_codes or payload.applicable_on or payload.rule_version)

def should_try_statute(plan, payload) -> bool:
    return (
        self.statute is not None
        and plan.handoff_target is None          # 明确转交的请求不查（spec 要求）
        and (plan.intent in STATUTE_INTENTS or scope_declared)
    )
```

- 备选：无条件把 `out_of_scope` 纳入 —— 否决：每条泛问题多 150ms，且与"用户没说法域"的语义不符。
- 备选：只对 `product_faq` 放宽 —— 否决：`out_of_scope` 才是最需要法规的一类（原产地、协定类问题）。

### D6 · 路由：显式范围的问题**重标为规则类**，而不是到处打补丁

实现时发现"超范围"在链路上有 **4 处短路**：`_general_route`（直连联网）、`_should_fallback`（intent 白名单）、`_standard_answer`（跳过检索）、`_compose`→`FixtureComposer`（直接返回 `unable_to_assess`）。逐处打补丁会留下四个互相依赖的判断。

因此改为**在 `analyze()` 之后重标一次**：当用户显式声明范围、且 `intent == out_of_scope`、无转交、无需澄清时，把 `intent` 置为 `trade_rule_explanation`，并记一条 `run scope boosted` 日志。语义上成立：用户指定了法域/日期/规则的问题，本来就是有范围的问题，不是"超出知识范围"。

```
analyze(...)
   │ scope_declared 且 out_of_scope 且 无转交/无澄清 ?
   │        是 -> intent = trade_rule_explanation（记 scope boosted 日志）
   v
_general_route(scope?) -> 否（intent 已不是 out_of_scope）
   v
标准检索（法规腿优先）── 有证据 ──> 回答（不联网）
   │无证据
   v
_should_fallback 按规则类判定 ──> 联网（仅当用户开启）
```

- 备选：逐处加 `not scope_declared` —— 实现后否掉：四处判断互相依赖，改一处就断链（已实测断在 `_standard_answer` 与 `_compose`）。
- 备选：保留 intent，只让 `FixtureComposer` 对"有证据的 out_of_scope"正常出 claim —— 否决：会改掉确定性 composer 已文档化的"超范围即无法评估"语义。
- 代价：`intent` 是可观察字段（日志/`route`），因此必须同时记 `scope boosted`，否则事后无法解释"为什么这条被判成规则类"。

### D7 · 默认不变即灰度

`scope_declared` 为假时不进入任何新分支：`should_try_statute` 退化为原来的 intent 判断，`_general_route`／`_should_fallback` 的条件不触发。因此不需要 feature flag；回滚只需隐藏控件（后端新分支自然不再进入）。

### D8 · 测试锚点

- 组件：填满三字段 → `createRun` 收到三字段；全空 → 三个 key 都不出现；`jurisdictions === null` → 控件禁用且不出现在请求里。
- 服务：`out_of_scope + scope_declared + 法规可用` → 有法规引用且**没有** web 层；`out_of_scope + scope_declared + 法规不可用 + web_search` → 走 web；`out_of_scope + scope_declared + web_search=false` → 不发起联网。
- 能力：法规源不可达 → `statute.jurisdictions is None`，且 capabilities 仍 200。

## Risks / Trade-offs

- [两处路由改动顺序写反 → "勾了联网却不联网" 或重复联网] → D6 的两条集成测试必须都写；评审时对照顺序图逐条核对。
- [显式范围下每条请求多一次跨服务调用（约 150ms）] → 仅 `scope_declared` 时发生；面板上写明 "Filters apply to statute retrieval only"。
- [法规源未配置时法域控件被禁用，看起来像功能缺失] → 文案明确 "not measured"，并保留"不限"可用；这比列出假法域更诚实。
- [规则版本被误解为能收窄检索] → 控件标签固定为 `Rule (applicability only)`，说明行写明不改变语料排序。
- [/v1/corpus/documents 需要 token；失败时 capabilities 可能 500] → 探测整体 try/except，失败只把 `jurisdictions` 置 `None`，不进异常路径。
- [用户在显式范围下期待"真法规"，结果因 `confidence=low` 回落本地语料] → 已有的 statute 层标签会显示降级原因；讨论过的"低置信回落"行为不得在本 change 被改掉。
- [English-only 装饰] → 新文案全部英文，`web/e2e/interface-language.spec.ts` 会拦住中文。

## Migration Plan

1. 后端增量先行：`StatuteCapability.jurisdictions` + 探测（失败即 `None`），跑通 capabilities 200。
2. `should_try_statute` 与两处路由改造，补齐三条服务测试；此时前端尚未发送范围，线上行为不变。
3. 前端控件与载荷映射，补组件测试与 e2e 文案。
4. 回滚：隐藏 `Scope (optional)` 一行即可 —— 后端新分支只在 `scope_declared` 为真时进入，不填范围等于回到旧路径；无数据迁移、无 schema 变更。

## Open Questions

- 是否需要多法域同时选择（API 已支持 ≤20；属于 UI 决策，可在后续 change 追加）。
- 范围是否要在会话/浏览器内持久化（现在只在组件 state 中，刷新即丢）。
- 是否把 `rule_version` 作为第二路检索串或写入回答说明 —— 需要先定 Answer 语义，暂缓。