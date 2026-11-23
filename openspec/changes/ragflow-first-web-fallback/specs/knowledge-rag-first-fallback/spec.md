# Spec Delta

## Purpose

规定知识问答的证据获取顺序：知识类问题必须先查 RAGFlow 语料（Mercatoria `/v1/retrieve`），命中交给豆包总结；只有语料没有返回任何文本时才自动联网，且联网仍受出站策略约束。

## ADDED Requirements

### Requirement: 知识类问题 MUST 先查询 RAG 语料

对产品 FAQ、规则解释与显式声明法域/交易日/规则版本的问题，系统 SHALL 在合成答案之前调用 `POST /v1/retrieve`，并把返回的文本条目放入本次证据包；规则类问题以其为主要证据，产品类问题与本地已发布语料共同参与。

#### Scenario: 规则问题先查 RAG

- **WHEN** 用户提问 `独立保函的定义是什么`
- **THEN** 本次运行先调用 `/v1/retrieve`，其命中进入证据包，并由豆包基于该命中生成回答

#### Scenario: 产品问题也先查 RAG

- **WHEN** 用户提问产品 FAQ（例如 `提交版本后编辑锁会释放吗？`）
- **THEN** 本次运行仍先调用 `/v1/retrieve`，且 RAG 命中与本地语料一起参与合成，不取代本地语料

#### Scenario: 文档选区问题保持快照为源

- **WHEN** 存在选中文本且用户提问 `这段条款是什么意思？`
- **THEN** 回答以选区快照为证据，RAG 命中不得覆盖或替换该选区证据

### Requirement: RAG 命中 MUST NOT 因置信度或覆盖范围被丢弃

服务返回的文本条目 SHALL 全部进入证据包并参与合成；`confidence=low`、`top score<0.6`、`requested_uncovered` 只 SHALL 作为回答中的限定说明，不得作为丢弃命中的条件。

#### Scenario: 低置信命中仍被采用

- **WHEN** `/v1/retrieve` 返回 5 条命中且 `confidence=low`
- **THEN** 这 5 条进入证据包，回答由豆包基于它们生成并注明"低置信，仅供参考"

#### Scenario: 法域未覆盖仍被采用

- **WHEN** 服务在 `requested_uncovered` 中声明请求的法域未被覆盖，同时返回了文本条目
- **THEN** 条目仍进入证据包，回答注明"该法域未被语料覆盖"，并给出命中条文能支持的部分

### Requirement: 豆包 MUST 总结命中，MUST NOT 仅因主题或法域不符拒答

合成阶段 SHALL 基于证据包输出可回答的部分，并说明证据的覆盖边界；系统 MUST NOT 因为"命中不是问题所指法域/主题的官方原文"而返回零引用的拒答。

#### Scenario: 问 WTO 但只有中国司法解释

- **WHEN** 用户提问 `guarantee在wto定义是什么` 且 RAG 只命中中国《独立保函规定》
- **THEN** 回答引用该司法解释并说明它不构成 WTO 框架下的定义，同时给出条文能支持的内容；不得返回零引用或"无法支撑"的拒答

#### Scenario: 低置信结果不再写"未采用"

- **WHEN** RAG 返回的命中被判为低置信
- **THEN** 回答仍使用这些命中，提示语为"低置信，仅供参考"，不得出现"命中 N 条但未采用"

### Requirement: 联网 MUST 仅在 RAG 无结果时自动尝试

仅当 `/v1/retrieve` 返回零条文本、调用失败或超时时，系统 SHALL 尝试豆包联网搜索；RAG 返回任意文本条目时 MUST NOT 发起联网请求。

#### Scenario: RAG 有条目则不联网

- **WHEN** RAG 返回至少一条文本条目
- **THEN** 本次运行不发起任何联网请求

#### Scenario: RAG 零结果时自动联网

- **WHEN** RAG 返回零条文本且用户未关闭联网
- **THEN** 系统自动调用豆包联网搜索，并用其结果合成回答

#### Scenario: RAG 服务失败不是"没有规定"

- **WHEN** `/v1/retrieve` 返回 503、超时或网络错误
- **THEN** 法规层记录失败原因（如 `corpus_updating` / `timeout`），并自动进入联网搜索；回答不得写成"没有相关规定"

#### Scenario: 用户显式关闭联网

- **WHEN** 用户关闭联网开关
- **THEN** 系统不发起联网请求，并在回答中说明本次未联网

### Requirement: 自动联网 MUST 受出站策略约束并留痕

自动联网请求 SHALL 在发出前经过出站策略判定，判定结果写入审计（用途、动作、原因、策略版本、查询摘要），回答 SHALL 标注联网内容为"未核验第三方内容"；策略缺失或判定拒绝时 MUST NOT 发出请求。

#### Scenario: 策略缺失时 fail-closed

- **WHEN** 出站策略未加载
- **THEN** 不发出联网请求，层状态为被阻止，回答说明因出站策略未联网

#### Scenario: 允许联网时留痕并标注

- **WHEN** 出站策略允许且联网返回结果
- **THEN** 审计出现一条允许记录（不含原文），回答引用标记为 `general_web` 并带"未核验第三方内容"提示

### Requirement: 两处皆无证据时 MUST 如实说明未找到

当 RAG（含失败）与联网都没有返回可用文本时，系统 SHALL 明确说明"知识库与联网都未找到"，MUST NOT 编造引用，也 MUST NOT 把该结果表述为"没有相关规定"。

#### Scenario: 两处皆空

- **WHEN** RAG 返回零条且联网返回零条
- **THEN** 回答说明两处都没有找到，且不包含任何引用

### Requirement: 来源标记 MUST 由引用推导

运行结果的来源标记 SHALL 依据实际引用计算：引用含法规条目时为 `statute`，仅由联网结果作答时为 `general_web`，仅由本地已发布语料作答时为 `published`；存在引用时 MUST NOT 为 `none`。

#### Scenario: 法规引用

- **WHEN** 回答引用了 `source_type="statute"` 的条目
- **THEN** `route` 为 `statute`

#### Scenario: 联网回退

- **WHEN** 回答仅由联网结果支撑
- **THEN** `route` 为 `general_web`，并带未核验提示