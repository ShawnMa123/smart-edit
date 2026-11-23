# Spec Delta

## Purpose

规定知识问答的法规腿改用 Mercatoria `/v1/chat` 获取「检索 + 草稿」，把引用与状态映射为本系统的证据与来源标记，并交给豆包做结构化/润色；同时定义无结果、超时、结构化失败时的回退与审计边界。

## ADDED Requirements

### Requirement: 法规腿 MUST 调用 `/v1/chat` 且 MUST NOT 调用 `/v1/retrieve`

对规则解释与显式声明法域/交易日/规则版本的问题，系统 SHALL 调用 `POST /v1/chat`（`answer.enabled=true`）获取检索与草稿；同一次运行 MUST NOT 调用 `/v1/retrieve`。

#### Scenario: 规则问题走 chat

- **WHEN** 用户提问 `独立保函的定义是什么`
- **THEN** 本次运行调用 `/v1/chat`，不调用 `/v1/retrieve`

#### Scenario: 不再产生 retrieve 调用

- **WHEN** 任一知识类问题完成了法规腿
- **THEN** 该运行的出站记录中只有一次 chat 调用，没有 retrieve 调用

### Requirement: chat 请求 MUST 使用脱敏问题与既有扩展词

系统 SHALL 发送出站闸判定后的 `question`，并把 `question + 扩展词` 作为 `retrieval_query`；`filters` 仍来自用户显式选择；MUST NOT 发送文档原文或选中片段。

#### Scenario: 脱敏后发送

- **WHEN** 问题包含 `USD 1,000,000` 且出站判定为脱敏
- **THEN** chat 请求中的 `question` 与 `retrieval_query` 都使用 `[redacted]` 版本，规则号保留

#### Scenario: 扩展词进入检索串

- **WHEN** 用户提问 `什么是guarantee`
- **THEN** `retrieval_query` 包含 `独立保函 / 见索即付保函 / demand guarantee / URDG 758`

### Requirement: chat 响应 MUST 映射为统一证据与引用

系统 SHALL 把 `references[]` 映射为证据（`chunk_id`、`doc_id`、`article_label`、`jurisdiction`、`effective_from/to`、score），**无论 `answer_status` 是什么**；`citations[]` 标记为 chat 已引用条目；`answer_status` SHALL 记录到法规层。只有当 `references` 为空时才视为没有 RAG 条文。

#### Scenario: answered 带引用

- **WHEN** chat 返回 `answer_status=answered` 且含 2 条 citations
- **THEN** 法规层记录 `detail=answered`，映射出带 locator 的 statute 证据，后续答案可引用

#### Scenario: unavailable 但有 references

- **WHEN** chat 返回 `answer_status=unavailable` 且 references 非空
- **THEN** 这些条文仍映射为证据并交给合成阶段，法规层记录 `detail=unavailable`，回答注明“服务自身的答案不可用”

#### Scenario: partial 仍可用

- **WHEN** chat 返回 `answer_status=partial`
- **THEN** 证据与草稿仍被使用，并在限制说明中写明依据不完整

### Requirement: chat 草稿 MUST 交给豆包结构化，且不得新增事实

当 chat 的 `answer_status` 为 `answered` 或 `partial` 时，合成阶段 SHALL 把 `answer` 作为 draft 交给豆包，要求其在给定证据 id 内结构化/润色；其他状态 MUST NOT 把 chat 的拒答文本作为 draft，只 SHALL 传递条文证据。最终 claims MUST 只引用证据 id，MUST NOT 引入 draft 中不存在的事实或来源。

#### Scenario: 最终答案引用证据

- **WHEN** chat 草稿引用了 2 个 chunk 且证据包含这 2 条
- **THEN** 最终答案的 claims 引用对应的证据 id，`route=statute`

#### Scenario: 草稿不作为新证据

- **WHEN** 豆包收到 draft
- **THEN** draft 只作为组织语言的输入，不得产生新的 citation id

#### Scenario: 拒答文本不作为草稿

- **WHEN** chat 返回 `unavailable/unsupported` 但有 references
- **THEN** 豆包只收到证据、不收到 chat 的拒答文本，仍从证据生成结构化答案

### Requirement: chat 零条文证据时 MUST 回退本地与联网

仅当 chat 返回 **零 references** 时，系统 SHALL 视为没有 RAG 文本，按既有规则回退本地已发布语料，并在需要时自动联网；当 references 非空但 `answer_status` 为 `unsupported/unavailable/error` 时，系统 SHALL 继续使用这些条文作为证据，并说明服务自身的答案不可用。MUST NOT 把任一结果表述为“没有相关规定”。

#### Scenario: unavailable 且有条文时不联网

- **WHEN** chat 返回 `answer_status=unavailable` 且 references 非空
- **THEN** 回答使用这些条文并由豆包结构化，法规层记录 `unavailable`，不触发联网

#### Scenario: 零条文才回退

- **WHEN** chat 返回零 references
- **THEN** 法规层记录无结果，回答改用本地语料（联网开启且仍无引用时自动联网）

#### Scenario: 服务失败不是零命中

- **WHEN** `/v1/chat` 返回 503 或超时
- **THEN** 法规层记录 `failed/<reason>`，随后进入本地与联网回退，不写成“没有规定”

### Requirement: 结构化失败 MUST 保留 chat 结果

当豆包结构化/润色失败、超时或拒答时，系统 SHALL 用 chat 返回的证据原文摘录作答并说明失败原因（有 draft 时说明“草稿已生成但结构化失败”，只有条文证据时说明“证据已返回但结构化失败”），MUST NOT 静默丢弃 chat 的结果。

#### Scenario: 豆包失败仍交付

- **WHEN** chat 已返回 answered，但豆包调用失败
- **THEN** 回答以证据摘录形式交付，并带“模型未完成结构化”的说明

#### Scenario: 只有条文证据时豆包失败

- **WHEN** chat 返回 `unavailable`（无 draft）但有 references，且豆包调用失败
- **THEN** 回答以证据摘录形式交付，并带“条文证据已返回但结构化失败”的说明

### Requirement: 产品 FAQ MUST NOT 调用 chat

产品 FAQ 与其它非规则问题 SHALL 继续只查本地已发布语料，MUST NOT 调用 `/v1/chat`。

#### Scenario: 产品问题不查法规

- **WHEN** 用户提问 `提交版本后编辑锁会释放吗？`
- **THEN** 本次运行不调用 `/v1/chat`，引用来自本地语料

### Requirement: chat 调用 MUST 留出站审计并写明端点

法规腿的每次 chat 调用 SHALL 先过出站策略，审计载荷 MUST 包含 `purpose="statute"`、`endpoint="chat"`、`action`、`reason`、`policy_version`、`query_digest`，且 MUST NOT 包含原文；策略缺失时 MUST NOT 发出请求。

#### Scenario: 允许时留痕

- **WHEN** 出站策略允许 chat 调用
- **THEN** 审计出现 `endpoint="chat"` 的允许记录，且不含问题原文

#### Scenario: 策略缺失 fail-closed

- **WHEN** 出站策略未加载
- **THEN** 不发出 chat 请求，法规层为 `blocked`，回答说明原因

### Requirement: chat 调用 MUST 使用独立超时预算

法规腿 SHALL 使用独立于检索层 5 秒预算的 chat 超时（可配置，默认 60s）；超时 SHALL 记录 `failed/timeout` 并回退，MUST NOT 因此让整次运行无答案。

#### Scenario: chat 较慢不拖垮检索层

- **WHEN** chat 调用耗时 20 秒
- **THEN** 法规层在自身预算内完成，本地/联网层仍按既有超时运行