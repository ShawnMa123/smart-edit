# Spec Delta

## Purpose

定义“通用联网”通道的边界：只回答**没有转交目标的范围外问题**，只允许一次只读 `web_search` 工具调用，结果一律标记为 `general_web` 未核验内容并封顶支持等级；该通道不得用于规则版本、适用范围或任何转交类请求。

## ADDED Requirements

### Requirement: 通用通道只有满足条件才启用

系统 SHALL 在同一轮运行同时满足“问题被判为 `out_of_scope` 且没有转交目标”**或**“标准路径没有任何可引用证据（回退）”其一，并且“用户显式开启联网”“部署显式允许通用联网”时调用通用通道；任一条件不满足时 MUST NOT 发起外部检索。

#### Scenario: 三个条件都满足

- **WHEN** 用户询问“今天有什么热点新闻”、显式开启联网，且部署允许通用联网
- **THEN** 系统 MAY 调用通用联网通道
- **AND** 运行 MUST 记录该通道被启用

#### Scenario: 已发布语料无法回答时回退

- **WHEN** 一个 in-scope 问题在标准路径上只得到“证据不足”且没有任何已发布引用，同时用户开启了联网
- **THEN** 系统 MAY 回退到通用通道
- **AND** 回答 MUST 同时标明“已发布语料未能回答”和“未核验第三方内容”
- **AND** 该回答 MUST NOT 支撑规则版本、生效日或适用范围

#### Scenario: 未开启或未允许

- **WHEN** 用户没有开启联网，或部署未允许通用联网
- **THEN** 系统 MUST NOT 调用任何外部检索
- **AND** 回答 MUST 按既有“范围外/证据不足”语义结束

### Requirement: 转交类问题永远不走通用通道

只要意图带有转交目标（改写、审查、法规建议），系统 MUST 走转交路径，MUST NOT 用联网结果代替转交。

#### Scenario: 改写请求

- **WHEN** 用户要求“帮我改写这段条款”，同时开启了联网
- **THEN** 回答 MUST 仍然是转交（`needs_handoff`）
- **AND** MUST NOT 调用通用联网通道

### Requirement: 通用通道只允许一次只读检索工具

通用通道的请求 SHALL 只包含一个 `web_search` 工具，关键字数量 MUST 有上限，MUST NOT 包含写操作、任意 URL 抓取或其他工具，且一次运行 MUST 只调用一次。

#### Scenario: 构造通用请求

- **WHEN** 系统调用通用联网
- **THEN** 请求体的 `tools` MUST 只有 `{"type": "web_search", "max_keyword": <= 配置上限}`
- **AND** MUST NOT 包含任何写入、执行或任意 URL 参数

#### Scenario: 工具调用失败

- **WHEN** 工具调用超时或返回错误
- **THEN** 回答 MUST 明确说明联网未完成
- **AND** MUST NOT 声称已联网核实

### Requirement: 通用联网结果一律标记为未核验

来自该通道的引用 SHALL 使用来源类型 `general_web`，并携带 `url`、`title` 与检索时间；回答 MUST 追加“未核验第三方内容”的说明，`support_level` MUST NOT 高于 `qualified`。

#### Scenario: 引用与标注

- **WHEN** 通用通道返回了带 URL 的结果
- **THEN** 每条引用 MUST 是 `general_web` 且带 `url` 与 `retrieved_at`
- **AND** 回答的 `limitations` MUST 包含未核验说明

#### Scenario: 规则类结论

- **WHEN** 问题涉及规则版本、生效日或适用范围
- **THEN** 这些结论 MUST NOT 由 `general_web` 证据支撑
- **AND** 系统 MUST 降级或改为“无法评估”

### Requirement: 准入域名在结果返回后过滤

通用通道的域名准入无法在调用前限定，因此系统 SHALL 对返回结果按配置的准入域名过滤；非准入域名 MUST NOT 成为引用。

#### Scenario: 命中准入域名

- **WHEN** 结果 URL 的主机属于准入清单
- **THEN** 该结果 MAY 作为 `general_web` 引用

#### Scenario: 全部被过滤

- **WHEN** 所有返回结果的域名都不在准入清单
- **THEN** 回答 MUST 说明“没有可用的准入来源”
- **AND** MUST NOT 用非准入域名凑数

### Requirement: 通用通道的决定与结果必须可审计

系统 SHALL 记录该通道的启用、工具、关键字上限、返回结果数与过滤丢弃数；MUST NOT 记录网页正文或用户身份。

#### Scenario: 审计内容

- **WHEN** 一轮通用联网结束
- **THEN** 审计 MUST 包含 `provider`、`tool`、`max_keyword`、`results`、`dropped`
- **AND** MUST NOT 包含网页正文或用户标识