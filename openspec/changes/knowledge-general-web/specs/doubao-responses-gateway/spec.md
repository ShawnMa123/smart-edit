# Spec Delta

## Purpose

定义知识助手撰写网关使用豆包 Ark **Responses API** 的契约：非流式请求、`input[]` 消息体、不带任何工具、结构化输出必须通过既有 `Answer` schema 校验，任何不合规响应都以失败结束而不是发布部分结果。

## ADDED Requirements

### Requirement: 撰写网关使用 Responses API

网关 SHALL 通过 `POST {base_url}/responses` 发起撰写请求，并使用该 API 的 `input` 消息体；MUST NOT 继续使用 `chat/completions` 的消息体。

#### Scenario: 发起撰写请求

- **WHEN** 服务端需要模型撰写答案
- **THEN** 请求 MUST 发送到 `{base_url}/responses`
- **AND** MUST 使用 `{"model": ..., "input": [{"role": "user", "content": [{"type": "input_text", "text": ...}]}]}` 形状
- **AND** MUST 设置 `stream: false`

#### Scenario: 响应解析

- **WHEN** 提供方返回非流式响应
- **THEN** 网关 MUST 从 `output` 中的文本内容提取一个 JSON 对象
- **AND** 缺少可用文本内容时 MUST 判定为失败

### Requirement: 结构化输出必须通过 schema 校验

网关 SHALL 只接受能通过 `Answer` 模型校验的 JSON；字段缺失、枚举越界或引用不存在的证据 ID 时 MUST 失败。

#### Scenario: 合法输出

- **WHEN** 响应 JSON 通过 `Answer` 校验且所有 citation 与 claim 引用的 ID 都在证据包内
- **THEN** 网关 MUST 返回该答案，交由既有复核流程继续处理

#### Scenario: 非法输出

- **WHEN** JSON 无法解析、字段缺失或引用了证据包外的 ID
- **THEN** 网关 MUST 以 `MODEL_OUTPUT_INVALID` 失败
- **AND** MUST NOT 返回“尽力解析”的结果

### Requirement: 撰写请求不携带工具

撰写调用 SHALL 只包含问题、证据包与必要指令，MUST NOT 携带 `tools`、`tool_choice` 或任意 URL。

#### Scenario: 构造请求体

- **WHEN** 网关构造撰写请求
- **THEN** 请求体 MUST NOT 包含 `tools` 或 `tool_choice`
- **AND** MUST NOT 包含数据库凭据、内部 URL 或可执行指令
- **AND** 模型 MUST NOT 能发起新的检索

### Requirement: 网关失败必须显式且不发布部分结果

网关 SHALL 把超时、非 200、非法 JSON 与校验失败映射为可区分的错误码；运行 MUST 以失败或超时结束，MUST NOT 发布部分答案。

#### Scenario: 超时

- **WHEN** 请求超过配置的超时时间
- **THEN** 网关 MUST 以 `MODEL_TIMEOUT` 失败
- **AND** 运行 MUST NOT 发布该次结果

#### Scenario: 提供方错误

- **WHEN** 提供方返回非 200
- **THEN** 网关 MUST 以 `PROVIDER_HTTP_<status>` 失败
- **AND** 错误 MUST 进入运行记录供排查