# Design

## Context

现状（见 `proposal.md` 的 Why）：

| 事实 | 位置 | 影响 |
|---|---|---|
| 没有能力查询端点 | `app/api/assistant.py`（只有 snapshots/sessions/runs/messages/citations） | 前端无法知道服务端能不能联网 |
| 通用通道依赖具体类 | `app/assistant/service.py:383` `isinstance(self.gateway, DoubaoGateway)` | fixture/替身网关无法演示，测试被迫构造真实类 |
| `skipped` 不渲染 | `web/src/components/KnowledgePanel.tsx:378-391` | “开关失效”完全靠猜 |
| 回答只有 `retrieval[]` 与 `processor` | `app/assistant/schemas.py` | 没有“走了哪条路 / 联网为什么没发生”的显式结论 |
| 部署开关散落 | `app/assistant/settings.py` | 能力端点需要把它们汇总成只读视图 |

## Goals / Non-Goals

**Goals:**

- 让前端在渲染前就知道：有没有模型、有没有通用联网、有没有准入 web 层。
- 让每条回答自带 `route` 与 `web` 摘要，界面据此解释“为什么没联网”。
- 把“网关是否支持搜索工具”从类名判断改为能力声明，保持 fail-closed。

**Non-Goals:**

- 配置收敛（`WEB_MODE`）与 `assistant_doctor.py`（W3，后续 change）。
- 允许 in-scope 问题使用联网（W4）。
- 改变检索策略、来源权威性或闸门规则。

## Decisions

### D1 能力端点：只读、无密钥、恒 200

```
GET /assistant/capabilities
{
  "model": {"configured": true, "label": "doubao:seed-2-1-lite", "approved_processor": true},
  "layers": {"local": true, "approved_web": false, "general_web": true},
  "egress": {"policy_version": "2026-11-16.1", "allowed_domains": 5, "loaded": true},
  "web": {"provider": "off|fixture|http"}
}
```

- 仍需经过身份解析（与其它端点一致），但不读工作区、不返回用户标识。
- `model.label` 只是 `provider:model`，不含 key；`egress` 只给版本与域名数量。
- 任何一项缺失都明确为 `false`，不使用“未知”。

### D2 网关能力标志

`DoubaoGateway.supports_tool_search = True`；其他实现默认没有该属性。路由改为：

```python
if not getattr(self.gateway, "supports_tool_search", False):
    return False
```

保持 fail-closed：未声明 = 不支持。测试可用一个 5 行的 stub 声明该标志，不再需要构造真实 provider。

### D3 `Answer` 增加 `route` 与 `web`

```python
Route = Literal["published", "document", "general_web", "handoff", "none"]

class WebSummary(Strict):
    requested: bool = False
    status: Literal["off", "skipped", "ok", "blocked", "failed"] = "off"
    reason: str | None = None
    hint: str | None = None

class Answer:
    ...
    route: Route | None = None      # 旧记录为 None
    web: WebSummary | None = None   # 旧记录为 None
```

两个字段都可空，保证历史消息反序列化不受影响。

### D4 `route` 的判定表（单一位置写入）

| 实际路径 | route |
|---|---|
| 文档选区解释 | `document` |
| 本地/发布语料检索后的回答 | `published` |
| 通用联网通道的回答 | `general_web` |
| 转交（`needs_handoff`） | `handoff` |
| 澄清、无法评估、失败、超时 | `none` |

写入点：`execute_run` 在答案定稿后、`commit_answer` 之前统一赋值；MUST NOT 由模型生成。

### D5 `web` 摘要与提示映射

服务端在同一个位置根据 `payload.web_search` 与 `layers` 生成 `WebSummary`：

| 情形 | status | reason | hint（UI 英文） |
|---|---|---|---|
| 未开启 | `off` | — | — |
| 无自建 provider | `skipped` | `web_unavailable` | `This server has no web provider configured.` |
| 通用通道未部署 | `skipped` | `tool_search_disabled` | `General web is disabled on this server.` |
| 处理器未批准 | `blocked` | `processor_not_approved` | `The model provider is not approved for outbound content.` |
| 选区泄露 | `blocked` | `contains_selection` | `Remove the document passage, then ask again.` |
| 超时/提供方错误 | `failed` | `timeout` / provider code | `Web search did not complete.` |
| 成功 | `ok` | — | — |

提示文案是界面语言（英文），与 `interface-language` 的“chrome 英文”一致；`limitations` 仍按回答语言生成。

### D6 面板状态矩阵

| 能力 | 开关 | 面板 |
|---|---|---|
| 无任何外部层 | 置灰 + 原因 | 顶部 `Web: not available on this server` |
| 只有 general_web | 可点，文案 `Ask general web (unverified)` | 回答显示 `route=general_web` 的未核验提示 |
| 有 approved_web | 可点，现有文案 | 来源分区 `Web` |
| 请求了但 skipped | — | 黄色 notice + hint（不再只写进 limitations） |
| in-scope 且请求了联网 | — | `Answered from published sources · web not needed` |
| 旧回答（无字段） | — | 不显示上述提示 |

### D7 兼容与验证

- 写库：`route`/`web` 随 `answer.model_dump()` 一起持久化；读取旧记录时为 `null`。
- 契约测试：能力端点不泄露密钥；`route` 与引用来源一致（`general_web` 回答的引用必须全是 `general_web`）。
- 面板测试：四种状态各一条；e2e 复用现有的 run 拦截替身。

## Risks / Trade-offs

- **能力端点泄露部署信息** → 只给布尔、版本与计数，不含 URL/key/用户；测试断言响应体不含 `key`、`token`、`http`。
- **`route` 与真实来源漂移** → 写入点唯一，并在测试中交叉断言 `route` 与 citations 一致。
- **前端缓存造成“开关可点但服务端已变”** → 每次打开面板或每次运行后刷新能力；失败时按“不可用”渲染。
- **旧记录显示不出原因** → 接受；新回答必须完整。

## Migration Plan

纯新增端点与可选字段，默认行为不变。回滚：前端不再调用能力端点、后端忽略新字段即可；不需要数据迁移。

## Open Questions

- 是否需要把能力响应也放进 `/healthz` 供运维使用（不影响本 change 的任务拆分）。