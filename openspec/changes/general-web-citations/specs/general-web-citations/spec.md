# Spec Delta

## Purpose

定义通用联网通道（`general_web`）在什么条件下可以产出引用：不受准入域名约束、必须带可解析链接、一律标注未核验、条数受限；并明确 `approved_web` 通道继续只接受准入域名。

## ADDED Requirements

### Requirement: 通用联网引用不受准入域名约束

`general_web` 通道的结果 MUST NOT 因域名不在准入清单而被丢弃；只要结果带有可解析的 http(s) 链接，就 MUST 可以作为引用出现在答案中。`approved_web` 通道 MUST 继续只接受准入域名，两条通道的策略互不影响。

#### Scenario: 结果来自非准入域名

- **WHEN** 通用联网检索返回一条来自公开词典或律所站点的结果
- **THEN** 该结果 MUST 被保留为引用，并带上其真实链接
- **AND** 答案 MUST 标注该内容为未核验

#### Scenario: 准入来源通道

- **WHEN** 证据来自 `approved_web` 通道且域名不在准入清单内
- **THEN** 该结果 MUST 被丢弃，行为与今天一致

### Requirement: 缺少可解析链接时不得产出引用

没有可解析 http(s) 链接的联网结果 MUST NOT 作为引用；当没有任何可用引用时，答案 MUST NOT 输出可发布的结论，并 MUST 说明"没有生成引用"而不是"没有相关规定"。

#### Scenario: 结果没有链接

- **WHEN** 联网结果缺少可解析链接
- **THEN** 该结果 MUST NOT 成为引用
- **AND** 若没有其它引用，答案结论 MUST 为证据不足

#### Scenario: 说明措辞

- **WHEN** 联网检索完成但没有任何可用引用
- **THEN** 限制说明 MUST 指出"未生成引用"，MUST NOT 归因于准入域名

### Requirement: 通用联网结论一律未核验且不得升为强支持

凡是引用通用联网证据的答案 MUST 携带未核验声明，且 MUST NOT 被标记为强支持；已发布来源的权威性 MUST NOT 通过与联网结果合并而提升。

#### Scenario: 引用联网结果

- **WHEN** 答案包含至少一条通用联网引用
- **THEN** 限制说明 MUST 包含未核验声明
- **AND** 支持等级 MUST NOT 为强支持

### Requirement: 联网被丢弃的结果必须可审计

当联网结果因缺少可解析链接而不可引用时，系统 MUST 在运行审计中记录其来源域名，使运维可以据此判断策略是否需要调整。

#### Scenario: 审计载荷

- **WHEN** 有联网结果被判定为不可引用
- **THEN** 审计记录 MUST 包含这些结果的来源域名列表
- **AND** MUST NOT 只记录被丢弃的数量