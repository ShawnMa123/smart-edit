# Spec Delta

## Purpose

定义一次知识问答如何组合三层证据——本地已发布语料、可选内部 RAG、可选联网——并保证联网只能作为受准入约束的补充证据：开关显式、来源可核验、与本地冲突不自动裁决、每层状态与抓取时间对用户可见。

## ADDED Requirements

### Requirement: 分层检索默认不联网且必须显式开启

系统 SHALL 默认只使用本地已发布语料与绑定的文档快照；联网层 MUST 由用户在本次提问时显式开启，MUST NOT 因会话、地区或模型推断而自动启用。

#### Scenario: 默认关闭

- **WHEN** 用户未开启联网就直接提问
- **THEN** 运行 MUST NOT 产生任何外部检索请求
- **AND** 回答 MUST 只引用本地已发布语料或文档快照

#### Scenario: 单轮开启

- **WHEN** 用户对某一次提问开启联网
- **THEN** 该次运行 MUST 记录已启用的证据层
- **AND** 后续未开启的提问 MUST NOT 继承该开关

### Requirement: 联网层只接受准入来源并保留可核验元数据

联网结果 SHALL 只来自配置的准入域名，并 MUST 携带足以复核的元数据：URL、域名、抓取时间、提供方与排序位次，以及可校验的正文片段。

#### Scenario: 命中准入来源

- **WHEN** 联网层返回一条准入域名内的结果
- **THEN** 该证据 MUST 以 `approved_web` 来源类型进入证据包
- **AND** MUST 携带 `locator{url, domain, retrieved_at, provider, rank}`
- **AND** 引用摘录 MUST 能在该结果保存的正文片段中被找到

#### Scenario: 准入来源之外的结果

- **WHEN** 检索结果来自未列入准入清单的域名
- **THEN** 系统 MUST 丢弃该结果
- **AND** MUST NOT 以任何形式把它计入证据或引用

#### Scenario: 联网失败或超时

- **WHEN** 联网层请求超时、限流或返回错误
- **THEN** 该层 MUST 被标记为失败
- **AND** 回答 MUST NOT 声称已联网核实
- **AND** 系统 MAY 继续使用其他层作答，并 MUST 说明联网未完成

### Requirement: 本地 RAG 层可替换且降级可见

本地第二层 SHALL 通过可替换适配器接入，允许在当前已发布语料检索与内部 RAG 服务之间切换；任一层失败时系统 MUST 显式说明降级，MUST NOT 静默以单层结果冒充完整检索。

#### Scenario: 切换到内部 RAG 服务

- **WHEN** 部署配置指向内部 RAG 服务
- **THEN** 检索 MUST 经由该适配器返回同样形状的证据候选
- **AND** 证据 MUST 保留来源版本与定位信息

#### Scenario: 第二层不可用

- **WHEN** 本地 RAG 适配器报错或超时
- **THEN** 回答 MUST 说明本地第二层未完成
- **AND** MUST NOT 把仅来自联网或仅来自文档快照的答案描述为“已完成两层检索”

### Requirement: 分层合并去重且来源权威分明

系统 SHALL 把多层候选合并为一个证据包并按来源去重；联网证据 MUST NOT 单独支撑最高等级的证据充分性，规则版本、生效日与适用范围 MUST 由本地已发布语料支撑。

#### Scenario: 仅有联网证据

- **WHEN** 回答的事实 Claim 只被联网证据支持
- **THEN** `support_level` MUST NOT 高于 `qualified`
- **AND** 回答 MUST 标注该证据为未核验的第三方内容

#### Scenario: 同一来源重复出现

- **WHEN** 多个层返回同一 URL 或同一发布来源的同一片段
- **THEN** 合并后 MUST 只保留一条证据
- **AND** MUST NOT 因重复出现而提高支持等级

#### Scenario: 本地与联网冲突

- **WHEN** 本地已发布语料与联网结果对同一规则给出不同表述
- **THEN** 系统 MUST 保留双方并标记冲突
- **AND** MUST NOT 自动选择其一作为结论
- **AND** 回答 MUST 降级或转人工确认

### Requirement: 每层状态与抓取时间对用户可见

回答 SHALL 让用户分辨哪些证据层被启用、成功或失败，以及联网证据的实际抓取时间；MUST NOT 用固定文案暗示实时性。

#### Scenario: 查看回答来源

- **WHEN** 用户查看一条完成了联网检索的回答
- **THEN** 回答 MUST 区分本地语料、联网与文档证据
- **AND** 每条联网证据 MUST 显示域名与抓取时间

#### Scenario: 检索发生在新旧版本之间

- **WHEN** 用户之后再次查看该回答
- **THEN** 显示的抓取时间 MUST 是该次运行的真实时间
- **AND** MUST NOT 更新为当前时间