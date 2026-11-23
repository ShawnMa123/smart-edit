# Design

## Context

现状（见 `proposal.md` 的 Why）：

| 事实 | 位置 | 影响 |
|---|---|---|
| 撰写网关走 `POST {base}/chat/completions` | `app/assistant/gateway.py:97` | 与可用的 Ark `responses` 契约不一致 |
| `out_of_scope` 在检索前短路 | `app/assistant/service.py:566` | “今天热点”类问题到不了模型 |
| 撰写路径 **不带 tools**，且规格明文禁止 | `assistant-model-gateway` R3 | 与 `web_search` 工具直接冲突 |
| 联网闸门只有 `search` / `compose` 两种 purpose | `app/assistant/egress.py` | 需要新增“工具检索”这一类外呼 |
| 现有联网结果来源是 `approved_web` | `app/assistant/retrieval.py` | 通用通道需要可区分的来源类型 |

用户提供的 Ark 调用样例（非本仓库代码）：

```
POST https://ark.cn-beijing.volces.com/api/v3/responses
{ "model": "doubao-seed-2-1-lite-260915",
  "stream": true,
  "tools": [{"type": "web_search", "max_keyword": 3}],
  "input": [{"role": "user", "content": [{"type": "input_text", "text": "..."}]}] }
```

本设计把它拆成两条互不混淆的调用：**撰写调用不带工具**、**通用联网调用只带 web_search**。

## Goals / Non-Goals

**Goals:**

- 撰写网关迁移到真实可用的 Responses API，并保持既有 schema 校验与复核。
- 让“范围外且非转交”的问题在用户显式开启时可以通过豆包联网作答。
- 通用答案与规则类答案在来源、支持等级与 UI 上完全可区分。

**Non-Goals:**

- 让通用联网参与规则/合规结论。
- 让豆包自带联网取代自建 web provider（`approved_web` 路径保持原样）。
- 流式输出、多轮工具调用、任意 URL 抓取。
- 真实第三方搜索 provider 的选型。

## Decisions

### D1 撰写调用：Responses API、非流式、无工具

```
POST {base}/responses
{ "model": ..., "stream": false,
  "input": [{"role": "system", "content": [{"type": "input_text", "text": SYSTEM}]},
            {"role": "user",   "content": [{"type": "input_text", "text": JSON_PAYLOAD}]}] }
```

- 解析：优先 `output_text`；否则遍历 `output[]`，取 `type == "message"` 的 `content[]` 中 `type == "output_text"` 的 `text` 拼接。
- 拼接结果必须是单个 JSON 对象，交给现有 `Answer.model_validate`；引用必须在证据包内。
- `stream:false`：现有运行是 202 + 轮询，流式只增加状态机复杂度，收益不足。
- 保留 `base_url` 默认 `https://ark.cn-beijing.volces.com/api/v3`，因此端点为 `…/api/v3/responses`。

### D2 路由优先级：转交 > 通用联网 > 标准检索

```
plan = analyze(question)
  |
  +-- handoff_target 非空 ---------------------> 转交（不变）
  |
  +-- intent == out_of_scope
  |     +-- web_search && general_web_enabled --> 通用联网通道
  |     +-- 否则 -----------------------------> unable_to_assess（不变）
  |
  +-- 其他 intent ------------------------------> 标准检索 + 撰写（不变）
```

通用通道的判断放在 `analyze` 之后、标准检索之前；不改变既有 in-scope 行为。

### D3 通用联网调用：单一只读工具

```
POST {base}/responses
{ "model": ..., "stream": false,
  "tools": [{"type": "web_search", "max_keyword": <= MAX_KEYWORD}],
  "input": [{"role": "user", "content": [{"type": "input_text", "text": SCREENED_QUESTION}]}] }
```

- 请求体 MUST NOT 含其它工具、写参数或任意 URL。
- `max_keyword` 由 `SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD` 控制（默认 3，上限 5）。
- 只发**经过闸门的查询**（沿用 `EgressInput(purpose="tool_search")`，见 D4）。
- 不做多轮：一次运行只发一次；工具结果不回流成第二次提问。

### D4 出站闸门的第三种 purpose

`EgressPolicy` 增加 `purpose="tool_search"`：

- 与 `compose` 一样要求 `provider_approved`（只有已批准处理方才能把查询转给其搜索后端）。
- 额外要求部署开关 `SMART_EDIT_ASSISTANT_GENERAL_WEB=1`，否则 `deny(tool_search_disabled)`。
- 审计记录 `provider`、`tool`、`max_keyword`、`action`、`reason`、`query_digest`（不含正文）。

### D5 引用映射与支持等级

豆包联网结果的引用来自响应中的 annotations（`url_citation` 形状待实现时确认）：

```
annotation -> Citation(
  id = sha1(url|title|start|end) 前 12 位,
  source_type = "general_web",
  title, source_version = retrieved_at,
  locator = {url, domain, retrieved_at, annotation_start, annotation_end}
)
```

- 新增 `SourceType` 值 `general_web`（Pydantic Literal + 前端联合类型）。
- 域名过滤：annotation 的 URL 主机必须命中 `egress.allowed_domains`；否则丢弃并计入 `dropped`。
- 支持等级：通用答案 `support_level` 封顶 `qualified`；若没有任何准入域名引用，则降为 `insufficient` 并说明原因。
- limitation：强制追加 `general_web` 未核验说明（中英文各一条）。
- 复核：通用答案走**精简复核**——citation ID 必须存在、claim 必须引用存在的 citation；不做“摘录⊆全文”校验（annotation 只有片段），这一点在 limitation 里明确写出。

### D6 UI

`KnowledgePanel`：

- 引用分区新增 `General web (n)`；条目显示 `domain · retrieved_at · Unverified third-party`。
- 当回答来自通用通道时，答案上方显示一条 `General web answer — unverified third-party content` 提示。
- 开关文案补充：`Off: only published sources…` / `On: also answers out-of-scope questions from the web (unverified)`。

### D7 预算与失败

| 阶段 | 预算 | 失败行为 |
|---|---|---|
| tool_search（通用联网） | 45s | 回答说明“联网未完成”，`support_level=insufficient` |
| compose（撰写） | 30s | `timed_out`，不发布部分结果 |

通用通道失败 MUST NOT 回退成“普通 in-scope 回答”，因为该问题本来就不在范围内。

### D8 配置

| 变量 | 默认 | 作用 |
|---|---|---|
| `SMART_EDIT_ASSISTANT_MODEL` | 空 | `doubao:<model>`，启用撰写网关 |
| `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED` | 0 | 允许向外发问题+证据包 |
| `SMART_EDIT_ASSISTANT_GENERAL_WEB` | 0 | 允许通用联网通道（额外一道开关） |
| `SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD` | 3 | 工具关键字上限（≤5） |

### D9 与未归档规格的合并顺序

`assistant-model-gateway`（chat/completions 约定）仍在未归档的 `knowledge-assistant-web-rag` 中。本 change 以其新能力 `doubao-responses-gateway` 承载新契约；两者归档时以本 change 为准，chat/completions 段落应删除或标注已取代。

## Risks / Trade-offs

- **API key 已在对话中暴露** → 必须轮换；代码只读环境变量，不落库。
- **外发面扩大** → `web_search` 会把查询交给提供方搜索后端；用双重开关（`PROCESSOR_APPROVED` + `GENERAL_WEB`）+ 闸门 + 审计控制。
- **域名准入只能事后过滤** → 可能“搜到了但全被丢弃”；回答必须明说，UI 也要显示 `dropped` 计数。
- **annotations 形状未验证** → 实现时先用一次真实调用确认；解析失败按“无引用”处理，仍给未核验答案。
- **延迟** → 工具调用明显更慢；独立 45s 预算，不拖垮 in-scope 路径。
- **注入** → 通用答案仍不调用其它工具、不写库；网页文本只用于组织回答，不改变权限。
- **两套来源并存** → `approved_web`（已准入、可全文复核）与 `general_web`（片段、未核验）必须在 UI 与 limitation 上清晰区分。

## Migration Plan

1. 先落 Responses 撰写网关（无行为变化，只有端点/解析变化），跑通现有测试。
2. 再加 `general_web` 类型、闸门 purpose 与审计（默认关闭）。
3. 打开 `GENERAL_WEB=1` 灰度验证，再更新文档与开关文案。
回滚：关闭 `SMART_EDIT_ASSISTANT_GENERAL_WEB`，行为回到“范围外不答”。

## Open Questions

- Ark 是否支持 Responses 的 JSON 强约束字段（类似 `text.format`）；若不支持，继续用“严格提示 + schema 校验”，不影响任务拆分。
- `web_search` 返回的 annotation 具体字段（`url_citation` 是否含 start/end、title）；实现时以真实响应为准，缺失字段时降级为仅 URL。
- 通用通道是否需要前端独立的“允许联网回答范围外问题”二次确认（当前设计只用同一个开关）。