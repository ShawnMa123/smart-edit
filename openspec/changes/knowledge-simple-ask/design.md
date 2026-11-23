# Design

## Context

动机见 `proposal.md`。塑造本设计的既有事实（均在本仓库核实）：

- **默认值是"关"**：`RunCreate.web_search` 默认 `False`；`service.py` 的 `_general_route()` 与 `_should_fallback()` 都以 `payload.web_search` 为第一条件。因此不勾选时，法规不可用只会停在 `insufficient_evidence`（已在端到端实测中复现）。
- **界面输入点共 5 个**：联网 checkbox、法域 select、`As of` date、`Rule` text、问题 textarea。
- **脱敏是代码**：`egress.py` 里 6 条正则写死（`amount_present / reference_present / account_number_present / email_present / url_present / variable_placeholder`），配置只提供 `allowed_domains / max_query_chars / selection_overlap_chars / extra_sensitive_terms`；文件缺失或损坏时**拒绝一切检索**。
- **规则编号豁免**：`_RULE_ID`（URDG/UCP/ISP/ISBP/URC/URR + 编号）在脱敏后会**被补回**检索串——这是"检索关键词不能被脱敏掉"的保护，属于不变量。
- **能力自检**目前只暴露 `web.provider`，没有默认值或预设清单。
- **规范冲突**：`knowledge-retrieval-layers`（"默认不联网且必须显式开启"）与 `knowledge-general-web`（通用通道启用条件）都还只在未归档的 change 中。

## Goals / Non-Goals

**Goals:**

- 页面上只剩 **1 个文本输入 + 1 个开关 + 1 行法域 chips**。
- 联网兜底默认开启，但**由部署决定**、用户可关，且每次运行可自证。
- 敏感信息预设是**数据**，同时保留三条安全不变量（fail closed、编译期失败、规则编号豁免不可配置）。
- 未设置任何新配置时，回滚只需要一个环境变量。

**Non-Goals:**

- 不做多法域同时选择，不做用户选择跨会话持久化。
- 不改那两个历史 change 的规范文件（见 D5 与 Open Questions）。
- 不做"静默联网"：开关始终存在，只是默认值变了。

## Decisions

### D1 · 默认值走三层：部署配置 → 能力自检 → 界面初值

```
SMART_EDIT_ASSISTANT_WEB_DEFAULT=on|off   （未设置 = on）
        │
        v
Capabilities.web.default_on = true        （前端不硬编码策略）
        │
        v
面板开关初值 = default_on；用户一经切换，以用户为准（本次挂载内记住）
        │
        v
每次运行仍显式发送 web_search: true|false
```

- 否决"前端 `useState(true)` 硬编码"：银行部署要能一键关掉，不该靠改前端。
- 否决"服务端在字段缺省时按默认处理"：那样运行记录无法自证"这次是否允许外呼"，且同一份请求在不同部署下行为不同。
- 前端处理能力异步到达的细节：用一个 `webTouched` 标记区分"用户已切换"与"仍在等能力"，避免能力晚到时覆盖用户的选择。

### D2 · 运行审计记录 `web_source`

运行审计载荷新增 `web_source: "user" | "default"`。仅凭 `web_search` 布尔无法区分"用户主动开的"和"部署默认开的"，而这在合规回溯时是第一个被问的问题。

### D3 · UI 只留法与 chips，删掉 `As of` 与 `Rule`

- `As of` 只影响 `filters.as_of`（时效），而该值在没有用户输入时本来就为空；删掉后行为等价于"按语料默认时效"。
- `Rule` 只用于消除"哪一版适用"的澄清，且服务端没有规则名过滤；保留它会让用户误以为能收窄检索。
- 法域改为 chips：选项来自配置预设（`scope_presets.jurisdictions`），**未测量/未配置时整行隐藏**，不显示假选项。

- 备选：保留下拉 —— 否决：点两下不如点一下，且下拉在 352px 面板里视觉更重。
- 备选：折叠成 `Advanced ▸` —— 否决：演示时要多一次点击才能看到能力。
- 备选：连法域也删 —— 保留：没有它就无法演示"WTO 下命中估价协定"这一最强证据。

### D4 · 配置文件：一份 JSON，加载优先级明确

```
SMART_EDIT_KNOWLEDGE_CONFIG 指定的路径（显式）
  > app/configs/knowledge.sample.json
  > app/configs/egress.yaml（兼容旧配置）
  > 都没有 → 拒绝一切外呼（沿用 egress 现有语义）
```

形状（节选，完整示例见 proposal）：

```jsonc
{
  "version": "2026-11-18.1",
  "egress": {
    "allowed_domains": ["..."],
    "max_query_chars": 400,
    "selection_overlap_chars": 40,
    "redactions": [{ "reason": "amount_present", "pattern": "..." }],
    "extra_sensitive_terms": ["..."]
  },
  "scope_presets": { "jurisdictions": ["CN", "EU", "INT", "US", "WTO"] },
  "suggested_questions": ["..."]
}
```

四条护栏（与 spec 一一对应）：

| 护栏 | 具体做法 |
|---|---|
| fail closed | 文件缺失/解析失败/结构非法 → `loaded=False`，`check()` 一律 deny（现有行为保持不变） |
| 编译期失败 | 启动时对每条 `pattern` 做 `re.compile`，任一失败即 `ValueError` 冒出（不静默跳过） |
| 豁免不可配置 | `_RULE_ID` 与"补回"逻辑保留在代码里；配置里**不提供**任何豁免字段，出现即忽略 |
| 防 ReDoS | `≤32` 条规则、单条 `≤512` 字符、单次 `re.sub` 带超时预算（超预算记 `pattern_timeout` 并拒绝外呼） |

- 否决"把 `extra_sensitive_terms` 扩展成正则列表"：自由正则 + 自由豁免是泄漏捷径；自由词已足够覆盖客户名/项目名。

### D5 · 规范处理：新能力 + 取代声明（S1）

`openspec/specs/` 下没有 `knowledge-retrieval-layers` / `knowledge-general-web`，因此不能写 `MODIFIED` delta。做法：新能力 `knowledge-web-fallback-policy` 拥有"默认值 + 可关 + 可审计"的行为，并在 proposal 里显式声明**取代**那两处默认值条款。

- 否决 S2（先归档旧 change 再改）：`knowledge-assistant-web-rag` 还差 1 条任务、`knowledge-general-web` 还差 1 条，收尾不属于本 change。
- 否决 S3（直接改别人的 change 文件）：会让在飞 change 的内容被外部改动，协作风险最高。
- 代价：一段时间内两份规范说法不同；已写入 Open Questions，并建议在旧 change 归档时清理。

### D6 · 知情成本：常驻一行说明

默认开启意味着**用户不做任何操作，问题就可能出网**。因此面板顶部常驻一行：

```
Statute-backed. If nothing matches, your question may go to public web search. You can turn it off.
```

配合已有的"联网证据一律未核验"标注，做到"知情 + 可关 + 可追溯"三件事同时成立。

## Risks / Trade-offs

- [默认开启让"用户没做任何操作就出网"] → 常驻说明 + 部署可关（`SMART_EDIT_ASSISTANT_WEB_DEFAULT=off`）+ 每次运行记 `web_source`；答案中的未核验标注继续强制。
- [出网次数上升，`stored question: redacted` 更频繁] → 这是脱敏在工作的表现；现有 UI 已有该文案，不需要新增说明。
- [配置里的正则写出灾难性回溯] → 条数/长度上限 + 编译期校验 + 每次替换的超时预算；超预算按"校验失败"拒绝外呼。
- [两份规范短暂矛盾] → 写在 Open Questions；建议旧 change 归档时按其 owner 流程删除默认值条款。
- [前端能力晚到覆盖用户选择] → `webTouched` 标记：用户点过之后不再应用默认值。
- [删掉 `As of` 后时效问题退化] → 该字段从未在界面被真正使用（无文档输入它的来源），删除不减少现有能力；需要时仍可通过 API 传。

## Migration Plan

1. **配置先行**：新增 `knowledge.sample.json` 与加载器（含四条护栏），此时 `egress.yaml` 继续生效，行为不变。
2. **默认值开关**：加 `SMART_EDIT_ASSISTANT_WEB_DEFAULT`（未设置 = `on`）、`Capabilities.web.default_on`、`web_source` 审计；后端先行，前端仍显式发送旧值，行为暂不变。
3. **前端切换**：删两个输入、法域改 chips、开关初值取能力、加常驻说明。
4. **回滚**：`SMART_EDIT_ASSISTANT_WEB_DEFAULT=off` 即回到"默认不联网"；若还要更彻底，隐藏 chips 行即回到上一版界面。无数据迁移、无 schema 变更。

## Open Questions

- `knowledge-retrieval-layers` 与 `knowledge-general-web` 里的默认值条款何时清理（建议随这两个 change 归档一并处理）。
- 用户的开关选择是否要跨会话记忆（当前只在组件挂载期内有效）。
- 法域 chips 是否需要多选（服务端 `filters.jurisdictions` 支持多个，本 change 只做单选）。