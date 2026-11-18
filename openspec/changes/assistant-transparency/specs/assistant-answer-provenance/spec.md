# Spec Delta

## Purpose

定义每条回答必须携带的“我来路”信息——走了哪条路径（已发布语料 / 文档 / 通用联网 / 转交 / 无）以及联网摘要（是否请求、结果状态、原因与提示），并规定界面在能力缺失、被跳过、被拦截与无需联网四种情形下如何表达。

## ADDED Requirements

### Requirement: 回答必须声明所用路径

每条新生成的回答 SHALL 在 `route` 中声明实际路径，取值为 `published | document | general_web | handoff | none`；MUST NOT 用“有引用”代替路径声明。

#### Scenario: 标准检索回答

- **WHEN** 回答基于已发布语料或文档快照
- **THEN** `route` MUST 为 `published` 或 `document`
- **AND** MUST NOT 声明为 `general_web`

#### Scenario: 通用联网回答

- **WHEN** 回答由通用联网通道产生
- **THEN** `route` MUST 为 `general_web`
- **AND** 其引用 MUST 全部是 `general_web`

#### Scenario: 转交与无结论

- **WHEN** 运行以转交、澄清或无法评估结束
- **THEN** `route` MUST 分别为 `handoff` 或 `none`
- **AND** MUST NOT 声明为 `published`

### Requirement: 回答必须携带联网摘要

每条新回答 SHALL 携带 `web` 摘要，说明是否请求联网、最终状态、原因码与用户可读提示；未请求联网时也 MUST 明确 `requested = false`。

#### Scenario: 请求了但被跳过

- **WHEN** 用户开启联网但该层不可用
- **THEN** `web.requested` MUST 为 `true`
- **AND** `web.status` MUST 为 `skipped`
- **AND** `web.reason` MUST 指明缺失项（如 `web_unavailable`）
- **AND** `web.hint` MUST 给出可执行的解释

#### Scenario: 被闸门拦截

- **WHEN** 出站判定拒绝
- **THEN** `web.status` MUST 为 `blocked`
- **AND** `web.reason` MUST 是判定理由码
- **AND** 提示 MUST 说明如何解除（去掉文档内容或关闭联网）

#### Scenario: 未请求联网

- **WHEN** 用户没有开启联网
- **THEN** `web.requested` MUST 为 `false`
- **AND** `web.status` MUST 为 `off`

### Requirement: 界面必须解释“为什么没联网”

界面 SHALL 根据能力与 `web` 摘要渲染明确状态；MUST NOT 在联网未发生时保持沉默。

#### Scenario: 服务端没有联网能力

- **WHEN** 能力响应表明没有任何外部联网层
- **THEN** 联网开关 MUST 不可用
- **AND** 界面 MUST 说明原因（例如“server has no web provider”）

#### Scenario: 开关可用但本次被跳过

- **WHEN** 用户开启联网而本次图层被跳过
- **THEN** 回答区域 MUST 显示 notice 与提示文本
- **AND** MUST NOT 只把说明放在 limitations 列表中

#### Scenario: 问题不需要联网

- **WHEN** 问题属于已发布语料可回答的范围且用户开启了联网
- **THEN** 界面 MUST 说明“answered from published sources · web not needed”
- **AND** MUST NOT 让用户误以为开关失效

### Requirement: 旧回答保持可读

缺少新字段的历史回答 SHALL 仍可读取；界面在缺少 `route`/`web` 时 MUST 退化为不显示对应提示。

#### Scenario: 读取旧消息

- **WHEN** 读取一条在本次变更之前生成的回答
- **THEN** 反序列化 MUST 成功
- **AND** 界面 MUST NOT 因缺少字段而报错或编造路径