# Spec Delta

## Purpose

定义 fixture 联网层的可复现契约：从版本化 JSON 文件加载准入页面，加载失败时保持"不可用"而不是静默空结果，并在配置正确时端到端产出可引用的 `approved_web` 证据，使本地演示能够验证"开启联网"这条链路。

## ADDED Requirements

### Requirement: fixture 联网层从配置文件加载页面

系统 SHALL 支持把 fixture 联网层的数据放在版本化 JSON 文件中；配置了该文件时，联网层 MUST 从文件读取页面，而不是返回空列表。

#### Scenario: 配置了有效文件

- **WHEN** `SMART_EDIT_ASSISTANT_WEB=fixture` 且提供了页面文件路径
- **THEN** 联网层 MUST 从该文件加载页面
- **AND** 每个页面 MUST 包含 `url`、`title` 与正文片段
- **AND** 加载结果 MUST 只保留通过准入域名过滤的页面

#### Scenario: 页面字段缺失

- **WHEN** 文件中某个条目缺少 `url`、`title` 或正文
- **THEN** 加载 MUST 失败并指出该条目
- **AND** 系统 MUST NOT 用部分页面继续启动

### Requirement: fixture 配置缺失或损坏时保持不可用

系统 SHALL 把缺失、空或无法解析的 fixture 配置视为"联网层不可用"，MUST NOT 把它当作"检索到 0 条结果"。

#### Scenario: 未提供文件路径

- **WHEN** `SMART_EDIT_ASSISTANT_WEB=fixture` 但没有提供页面文件路径
- **THEN** 启动后联网层 MUST NOT 被装配
- **AND** 开启联网的运行 MUST 报告该层不可用（`web_unavailable`）

#### Scenario: 文件无法解析

- **WHEN** 页面文件不存在或不是合法 JSON
- **THEN** 启动 MUST 失败并给出可读错误
- **AND** MUST NOT 静默退化为空的联网结果

### Requirement: 配置正确时必须端到端产出联网证据

当 fixture 配置正确时，开启联网的一轮问答 SHALL 在回答中给出 `approved_web` 引用，并保留可核验的定位信息。

#### Scenario: 开启联网的一轮

- **WHEN** 用户在配置了 fixture 页面的环境中对网页可覆盖的问题开启联网
- **THEN** 回答 MUST 至少包含一条 `source_type=approved_web` 的引用
- **AND** 该引用 MUST 携带 `url`、`domain` 与 `retrieved_at`
- **AND** 运行的 `retrieval` MUST 把 web 层标记为 `ok`

#### Scenario: 未开启联网

- **WHEN** 用户没有开启联网
- **THEN** 即使配置了 fixture 页面，系统 MUST NOT 产生 `approved_web` 引用

### Requirement: 本地验证入口不依赖 HTTP 服务

系统 SHALL 提供一条本地命令，在不启动 HTTP 服务的情况下跑通"会话创建 → 提问 → 检索 → 回答"，并打印可核对的摘要。

#### Scenario: 运行验证命令

- **WHEN** 开发者运行该命令并指定联网开关
- **THEN** 输出 MUST 包含本次运行的 `outcome`、`retrieval` 层状态与引用列表
- **AND** 命令 MUST 使用临时数据库，不修改本地 `runs/assistant.db`