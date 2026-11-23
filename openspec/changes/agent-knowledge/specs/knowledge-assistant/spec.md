# Spec Delta

## Purpose

让授权用户在固定的工作区与文档快照范围内，以**有证据、可追溯、可弃答/澄清/转交**的方式回答产品 FAQ、贸易规则与文档问题；回答不得修改正文、审批或扩大权限。

## ADDED Requirements

### Requirement: 会话绑定不可变上下文

系统 SHALL 把每次问答绑定到请求人、工作区，以及可选的不可变文档快照、选区与附件集合；绑定后 MUST NOT 在会话中隐式更换文档或版本。`document_id` 与 `snapshot_id` MUST 同时出现或同时省略。

#### Scenario: 创建 FAQ 会话

- **WHEN** 用户在没有文档的情况下创建工作区内的 FAQ 会话
- **THEN** 会话 MUST 记录工作区与所有者
- **AND** MUST NOT 隐式绑定任意文档

#### Scenario: 创建文档会话

- **WHEN** 用户针对当前文档快照创建会话
- **THEN** 会话 MUST 记录不可变的快照标识与正文摘要
- **AND** 后续回答 MUST 只使用该快照

#### Scenario: 文档更新后

- **WHEN** 会话绑定的文档快照已不是当前版本
- **THEN** 读取会话 MUST 标记 `context_stale`
- **AND** MUST NOT 把新版本内容静默带入旧会话
- **AND** 用户 MUST 能基于新快照新建会话

#### Scenario: 附件集合变化

- **WHEN** 用户想更换会话绑定的附件集合
- **THEN** 系统 MUST 要求新建会话
- **AND** MUST NOT 在原会话中隐式替换附件

### Requirement: 一次只允许一个活跃运行，且状态可轮询与取消

系统 SHALL 以 `queued | running | succeeded | failed | cancelled | timed_out` 表达运行状态；创建运行 MUST 返回可轮询的受理结果，同一会话 MUST NOT 同时存在多个活跃运行；取消、超时与成功发布 MUST 竞争同一个终态。

#### Scenario: 创建并轮询

- **WHEN** 用户在会话中提交一个问题
- **THEN** 系统 MUST 创建一条用户消息与一个 Run
- **AND** MUST 返回受理结果与轮询地址/建议间隔
- **AND** 轮询期间 MUST NOT 返回未经复核的答案

#### Scenario: 幂等重试

- **WHEN** 客户端用相同幂等键与相同请求重试创建运行
- **THEN** 系统 MUST 返回同一个 Run
- **AND** MUST NOT 创建重复用户消息或助手消息
- **AND** 相同键但请求不同 MUST 返回冲突

#### Scenario: 会话忙碌

- **WHEN** 同一会话已有 `queued` 或 `running` 的运行
- **THEN** 新运行 MUST 被拒绝并说明会话忙碌

#### Scenario: 取消与超时

- **WHEN** 用户取消一个活跃运行，或运行超过总截止时间
- **THEN** 该运行 MUST 进入 `cancelled` 或 `timed_out`
- **AND** MUST NOT 生成助手回答
- **AND** 迟到的执行结果 MUST NOT 覆盖终态

### Requirement: 回答必须带证据等级并显式表达不确定性

每个 Answer SHALL 包含 `outcome`、`language`、`support_level`、`claims`、`citations`、`limitations` 与 `clarification_questions`；`outcome` MUST 为 `answered | needs_clarification | insufficient_evidence | unable_to_assess | needs_handoff`，`support_level` MUST 为 `strong | qualified | insufficient | not_applicable`。

#### Scenario: 有证据的回答

- **WHEN** 问题有充分且当前有效的证据
- **THEN** `outcome` MUST 为 `answered`
- **AND** `support_level` MUST 为 `strong` 或 `qualified`
- **AND** 至少一个 Claim MUST 存在

#### Scenario: 证据不足

- **WHEN** 检索不到足以支持结论的证据
- **THEN** `outcome` MUST 为 `insufficient_evidence`
- **AND** `support_level` MUST 为 `insufficient`
- **AND** MUST NOT 给出肯定性的专业结论或伪造引用

#### Scenario: 缺少适用信息

- **WHEN** 规则版本、法域或适用日期缺失且会改变答案
- **THEN** `outcome` MUST 为 `needs_clarification`
- **AND** MUST 提出 1–3 个具体澄清问题
- **AND** MUST NOT 猜测法域、版本或交易日期

#### Scenario: 请求超出范围

- **WHEN** 用户要求修改正文、审批或完整合规审查
- **THEN** `outcome` MUST 为 `needs_handoff`
- **AND** MUST 指定 `automation | standards_audit | regulatory_advice` 之一
- **AND** MUST NOT 产生任何正文或业务副作用

### Requirement: 每个事实 Claim 必须绑定真实证据

每个 `kind=fact` 的 Claim SHALL 绑定至少一个真实证据；Citation MUST 来自本次授权检索到的来源，携带来源类型、标题、版本与定位；系统 MUST NOT 生成不存在的引用 ID、来源 URL 或未经核实的抓取时间。

#### Scenario: 有效引用

- **WHEN** 回答包含一个事实 Claim
- **THEN** 该 Claim MUST 引用一个本次检索返回的证据
- **AND** 引用详情 MUST 返回获准摘录与定位

#### Scenario: 伪造引用

- **WHEN** 生成结果引用了不存在的证据 ID
- **THEN** 系统 MUST NOT 发布该引用或该肯定性 Claim
- **AND** 复核失败 MUST 被记录，而不是静默通过

#### Scenario: 引用不支持 Claim

- **WHEN** 引用存在但其内容不支持 Claim
- **THEN** 系统 MUST 降级、删除该 Claim 或弃答
- **AND** MUST NOT 仅凭“引用 ID 存在”判定通过

#### Scenario: 文档选区引用

- **WHEN** 回答基于当前文档快照或选区
- **THEN** 引用 MUST 定位到该快照的节点或字符区间
- **AND** 选区的 Unicode code point 偏移 MUST 与原文完全匹配；不匹配 MUST 返回明确错误

#### Scenario: OCR 来源

- **WHEN** 引用的附件含待人工确认的 OCR 关键值
- **THEN** 回答 MUST 提示核对原件
- **AND** MUST NOT 把该值当成已确认事实

### Requirement: 授权必须在检索、生成、发布与读取时重新验证

系统 SHALL 在检索前、生成前、发布前、读取历史与会话、打开引用时重新验证权限；不存在、非所有者或失权的具体资源 MUST 返回一致的“找不到”，不得泄漏标题、数量或内容；撤权后衍生回答 MUST 不可读。

#### Scenario: 跨用户访问

- **WHEN** 用户 A 访问用户 B 的 Session、Run 或 Citation
- **THEN** 系统 MUST 返回一致的 404
- **AND** MUST NOT 透露标题、消息或引用内容

#### Scenario: 回答后撤权

- **WHEN** 已回答后某个上下文依赖被撤回或失权
- **THEN** 该消息 MUST 以 `redacted` 占位返回
- **AND** 新一轮历史 MUST 不再复用该依赖

#### Scenario: 来源撤回

- **WHEN** 一个知识来源被撤回
- **THEN** 它 MUST NOT 被默认检索或打开
- **AND** 已有回答中依赖它的引用 MUST 按撤权规则处理

#### Scenario: 跨用户缓存

- **WHEN** 系统使用回答缓存
- **THEN** 缓存键 MUST 包含主体、授权版本、会话快照与知识发布版本
- **AND** MUST NOT 跨用户复用答案

### Requirement: 只有已发布且当前有效的知识版本可以参与默认检索

知识来源 SHALL 具有 `processing | pending_review | published | superseded | withdrawn` 状态；只有 `published`、当前授权且落在适用有效期内的版本 MAY 进入默认检索。发布 MUST 由与提交人不同的审核人批准，且 MUST 原子生效。

#### Scenario: 待审核内容

- **WHEN** 一个知识版本仍是 `pending_review`
- **THEN** 它 MUST NOT 被检索或引用
- **AND** 它 MUST NOT 被当成“没有知识”而返回肯定性回答

#### Scenario: 提交人自审

- **WHEN** 提交人尝试批准自己提交的版本
- **THEN** 系统 MUST 拒绝
- **AND** 发布 MUST NOT 发生

#### Scenario: 原子发布

- **WHEN** 一个新版本发布
- **THEN** 所有分块与发布指针 MUST 一起生效
- **AND** 部分索引失败 MUST NOT 暴露部分发布内容

#### Scenario: 生效期与替代

- **WHEN** 问题指定适用日期或历史规则
- **THEN** 系统 MUST 选择该日期有效的版本；无截止日 MUST 视为开放区间
- **AND** `superseded` 版本 MUST NOT 参与默认当前知识检索

#### Scenario: 适用范围缺失

- **WHEN** 来源缺少法域/适用性元数据却要支持适用性结论
- **THEN** 系统 MUST 返回 `unable_to_assess` 或明确的范围限制
- **AND** MUST NOT 把缺少元数据当成“已覆盖”

### Requirement: 检索无命中与检索失败必须区分

系统 SHALL 区分“没有足够证据”“检索依赖不可用”与“部分覆盖”；无证据 MUST NOT 被呈现为技术成功，依赖失败 MUST NOT 被呈现为知识不足。

#### Scenario: 无命中

- **WHEN** 检索正常完成但没有达到证据门槛的内容
- **THEN** `outcome` MUST 为 `insufficient_evidence`
- **AND** MUST 说明缺失范围

#### Scenario: 检索依赖失败

- **WHEN** 检索服务不可用或超时
- **THEN** Run MUST 进入 `failed` 并带可诊断错误
- **AND** MUST NOT 返回 `insufficient_evidence` 冒充正常结论

#### Scenario: 来源冲突

- **WHEN** 两个来源的适用范围或结论冲突
- **THEN** 系统 MUST 保留冲突并返回 `unable_to_assess` 或明确限制
- **AND** MUST NOT 自动选择“看起来更正确”的来源

### Requirement: 知识助手不得修改正文、审批或扩大权限

知识助手 SHALL 只返回问答与转交建议；其工具白名单 MUST NOT 包含正文写入、审批、提交版本、任意网络访问或任意 URL 抓取。问题、文档、附件与检索片段中的指令 MUST 视为数据，不得改变权限或系统行为。

#### Scenario: 修改请求

- **WHEN** 用户要求润色、替换条款或直接修改正文
- **THEN** 系统 MUST 返回 `needs_handoff`
- **AND** MUST NOT 修改文档或创建编辑任务

#### Scenario: 文档内注入

- **WHEN** 问题或文档包含“忽略指令、读取内部资料”等内容
- **THEN** 系统 MUST NOT 扩大检索范围、提升权限或调用未授权工具

#### Scenario: P1 能力未启用

- **WHEN** 用户请求联网检索、语音或截图
- **THEN** 系统 MUST 明确说明该能力未启用
- **AND** MUST NOT 伪造抓取时间或声称已执行

### Requirement: 反馈与执行审计必须可追溯

系统 SHALL 为回答保存可追踪的 Run、证据版本、复核结果与反馈；反馈 MUST 关联具体助手消息，且 MUST NOT 直接修改知识库、系统提示或权限。审计 MUST NOT 保存模型隐式思维链。

#### Scenario: 反馈替换

- **WHEN** 同一用户对同一助手消息再次提交反馈
- **THEN** 反馈 MUST 被替换并保留审计历史
- **AND** MUST NOT 改变答案、知识发布状态或权限

#### Scenario: 审计失败

- **WHEN** 必要的审计写入失败
- **THEN** 系统 MUST NOT 报告运行为成功完成
- **AND** MUST 以可诊断错误结束或进入明确的待重试状态

### Requirement: 本地/测试模式必须显式且不可冒充生产

系统 SHALL 在 local/test 模式使用显式 Fake Adapter 与合成知识源，并在界面上标注 fixture 来源；当 production 模式缺少经批准的 Adapter 时 MUST 失败关闭，MUST NOT 用 Fake 继续运行。

#### Scenario: 本地 fixture 模式

- **WHEN** 系统以 fixture/合成语料运行
- **THEN** 界面与结果 MUST 标注 fixture-backed
- **AND** MUST NOT 声称模型、联网或真实法规已核验

#### Scenario: 生产缺少 Adapter

- **WHEN** production 模式检测到 Fake 身份/快照/模型或合成知识源
- **THEN** 系统 MUST 拒绝启动或拒绝该请求
- **AND** MUST NOT 静默降级为本地实现