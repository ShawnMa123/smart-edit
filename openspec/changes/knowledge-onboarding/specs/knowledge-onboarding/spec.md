# Spec Delta

## Purpose

为首次使用知识助手的用户提供诚实的能做什么 / 不能做什么 / 如何提问引导，并让能力问题从已发布帮助来源返回带引用的回答。

## ADDED Requirements

### Requirement: 首次使用引导可见且诚实

知识面板 SHALL 在用户首次打开知识 tab 时以**英文**显示可折叠的引导卡片，说明助手能做什么、不能做什么、如何提问，并明确标注合成或 fixture 来源；引导 MUST NOT 渲染示例答案、示例引用，或把未实现能力说成可用。

#### Scenario: 首次打开知识面板

- **WHEN** 用户首次打开 Knowledge Q&A tab
- **THEN** 面板 MUST 显示英文引导卡片，包含 Can / Cannot / How 三类说明
- **AND** MUST 显示 `Fixture-backed` 或等价的合成来源声明
- **AND** MUST NOT 渲染示例答案、示例引用或未发生的 Run

#### Scenario: 英文引导的默认语言

- **WHEN** 面板未显式选择其它 locale
- **THEN** onboarding 文案和快捷问题 MUST 使用英文
- **AND** 不得因为知识语料是中文而把引导退回中文

#### Scenario: 文档问题缺少选区

- **WHEN** 用户已打开文档但没有选中文字
- **THEN** 引导 MUST 说明文档问题需要先选中一段文字
- **AND** MUST NOT 建议“总结全文”等当前不支持的问法

### Requirement: 快捷问题必须可回答且不产生副作用

面板 SHALL 提供最多 3 个英文快捷问题；英文问题 MUST 属于当前构建支持的能力，产品/规则事实问题 MUST 有对应的英文语料可回答；点击 MUST 只把问题填入输入框并聚焦，MUST NOT 自动创建 Run、写入正文或提交任何操作；第一次回答后快捷问题可以折叠，但 MUST 可恢复。

#### Scenario: 无选区时的默认快捷问题

- **WHEN** 用户没有选中文字
- **THEN** 面板 MUST 提供最多 3 个英文快捷问题，至少覆盖能力帮助、产品事实、规则事实
- **AND** 每个快捷问题 MUST 能通过英文知识语料回答，或明确导向澄清/转交

#### Scenario: 有选区时的快捷问题

- **WHEN** 用户选中了一段文字
- **THEN** 快捷问题 MUST 包含英文的 `What does this passage mean?`
- **AND** MUST 仍然最多 3 个

#### Scenario: 点击快捷问题

- **WHEN** 用户点击一个快捷问题
- **THEN** 面板 MUST 将问题填入输入框并聚焦
- **AND** MUST NOT 自动创建 Session、Run 或 Message
- **AND** MUST NOT 修改文档内容

#### Scenario: 不提供未实现能力

- **WHEN** 面板渲染快捷问题
- **THEN** MUST NOT 提供“总结全文”“修改条款”“联网查法规”等当前未实现或不支持的建议

#### Scenario: 回答后折叠

- **WHEN** 用户完成第一次回答
- **THEN** 快捷问题 MAY 折叠
- **AND** 用户 MUST 能通过 `Show examples` 或等价入口恢复

### Requirement: 能力帮助问题从已发布帮助来源回答

用户询问 `What can you do?`、`How should I ask?`、`What questions can I ask?` 或中文等价问题时，系统 SHALL 按问题语言选择对应语言的已发布帮助来源，并通过既有 Answer 合同返回 `answered`、至少一个 Claim 和来自该帮助来源的 Citation；MUST NOT 用模型记忆、系统提示词或未发布内容回答能力问题。

#### Scenario: 询问能做什么（英文）

- **WHEN** 用户问 `What can you do?` 且英文帮助来源已发布
- **THEN** `outcome` MUST 为 `answered`
- **AND** `language` MUST 为 `en`
- **AND** `support_level` MUST 为 `strong` 或 `qualified`
- **AND** 至少一个 Claim MUST 说明支持的能力，并引用英文帮助来源的 chunk

#### Scenario: 询问能做什么（中文）

- **WHEN** 用户问中文能力问题且中文帮助来源已发布
- **THEN** 回答 MUST 使用中文帮助来源
- **AND** MUST NOT 引用英文帮助来源或返回中英混排正文

#### Scenario: 询问如何提问

- **WHEN** 用户问 `How should I ask a question?` 或 `What questions can I ask?`
- **THEN** 回答 MUST 说明需要规则名/版本/法域/日期，以及文档问题需要选区等问法
- **AND** MUST 引用对应语言的帮助来源，而不是仅返回通用寒暄

#### Scenario: 帮助来源未发布或缺失

- **WHEN** 对应语言的帮助来源仍是 `pending_review`、`superseded` 或 `withdrawn`
- **THEN** 系统 MUST NOT 检索或引用该来源
- **AND** MUST NOT 凭记忆声称助手具备某项能力
- **AND** MAY 返回 `insufficient_evidence` 并明确说明帮助指南未就绪

### Requirement: 帮助来源与其它知识源使用相同的治理规则

帮助来源 SHALL 使用与其它知识源相同的 source / version / chunk 元数据，标注 synthetic、版本、语言、生效期、scope 与审核人；只有 `published` 且当前有效的版本 MAY 参与默认检索；撤回后 MUST 不再被检索或打开，已有回答 MUST 按既有撤权规则处理。

#### Scenario: 帮助来源发布

- **WHEN** 中文或英文帮助来源通过审核并发布
- **THEN** 它 MUST 可在对应语言的问题中被默认检索
- **AND** Citation MUST 携带标题、版本与定位

#### Scenario: 帮助来源撤回

- **WHEN** 帮助来源被撤回
- **THEN** 它 MUST NOT 被默认检索
- **AND** 依赖它的历史消息 MUST 以 `redacted` 占位返回
- **AND** 打开其 Citation MUST 返回一致的“找不到”

#### Scenario: 新版本替代

- **WHEN** 帮助来源的新版本发布
- **THEN** 旧版本 MUST 变为 `superseded`
- **AND** 默认检索 MUST 只使用新版本

#### Scenario: 普通问题不使用帮助来源

- **WHEN** 用户询问产品、规则或文档内容，而不是能力/使用方式
- **THEN** 检索 MUST NOT 返回帮助来源的 chunk
- **AND** 回答 MUST NOT 把帮助指南当作产品/规则证据引用

### Requirement: 并行语言来源不得混用

当同一主题存在多语言来源时，系统 SHALL 为每个 Run 选择与问题语言一致的来源；MUST NOT 在同一答案中混用不同语言的来源，以免产生跨语言冲突或中英混排正文。

#### Scenario: 英文问题

- **WHEN** 用户用英文询问产品、规则或能力问题
- **THEN** 检索 MUST 只返回英文来源
- **AND** Claim 与 limitation MUST 使用英文
- **AND** Citation MUST 指向英文来源

#### Scenario: 中文问题

- **WHEN** 用户用中文询问产品、规则或能力问题
- **THEN** 检索 MUST 只返回中文来源
- **AND** Claim 与 limitation MUST 使用中文
- **AND** Citation MUST 指向中文来源

#### Scenario: 语言来源缺失

- **WHEN** 问题语言对应的来源不存在
- **THEN** 系统 MUST 返回 `insufficient_evidence` 或明确的能力未就绪说明
- **AND** MUST NOT 回退到另一种语言的来源并声称已回答

### Requirement: 本地/测试 fixture 必须补齐

local/test 模式 SHALL 在启动时检测已有数据库并补种/升级当前构建所需的 fixture source 与 version；旧数据库缺少帮助来源时 MUST 补齐，若无法补齐 MUST 以明确诊断失败，不得让内置帮助问题落到 `insufficient_evidence`。

#### Scenario: 旧的本地数据库

- **WHEN** `runs/assistant.db` 只有旧的 3 个 source，缺少新的帮助来源
- **THEN** local/test 启动 MUST 补种缺失 fixture source 或升级 version
- **AND** 重启后 `What can you do?` / `你能做什么？` MUST 能回答
- **AND** MUST NOT 重复创建同一 source/version

#### Scenario: 补种失败

- **WHEN** local/test 启动无法补齐 fixture source
- **THEN** 启动 MUST 失败并给出可诊断错误
- **AND** MUST NOT 以 `insufficient_evidence` 伪装成“没有知识”

### Requirement: 引导与帮助不得扩大能力或绕过转交

引导卡片和帮助回答 MUST NOT 声称助手可以修改正文、审批、提交、联网、语音/截图或提供法律结论；对修改、审批、完整审查等请求 MUST 继续返回 `needs_handoff`，且 MUST NOT 产生正文或业务副作用。

#### Scenario: 询问能否修改文档

- **WHEN** 用户问“你能修改文档吗？”或要求修改正文
- **THEN** 系统 MUST 返回 `needs_handoff`
- **AND** `handoff_target` MUST 为 `automation` 或 `standards_audit`
- **AND** MUST NOT 修改文档或创建编辑任务

#### Scenario: 引导说明不能做什么

- **WHEN** 用户阅读引导卡片的 Cannot 部分
- **THEN** 它 MUST 至少列出修改正文、审批/提交、联网/法律结论中的边界
- **AND** MUST NOT 暗示这些能力已实现

#### Scenario: 回答涉及法规或合规

- **WHEN** 帮助回答提到规则、法规或合规判断
- **THEN** MUST 说明只解释已发布来源、不构成法律意见
- **AND** MUST NOT 声称已完成真实法规核验或制裁筛查