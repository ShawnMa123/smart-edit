# Spec Delta

## Purpose

规定法律审查模块（`/legal/*`）的契约与行为：`modes=["legal"]` 复用 `/v1/chat` 把法规建议映射为可追溯的 Finding；同时以诚实性不变量保证「没检查/答不了」绝不被展示成「没问题」。

## ADDED Requirements

### Requirement: 法规回答 MUST 以 `answer_status` 判定可用性

系统 SHALL 以服务返回的 `answer_status` 判定是否产出 Finding：`answered`/`partial` SHALL 产出 Finding；`unavailable`/`unsupported`/`error` 或零引用 SHALL 记为 `unable_to_assess`，且 MUST NOT 把服务返回的无关联 references 展示为引用。

#### Scenario: 离题问题不硬凑

- **WHEN** 服务对离题问题返回 `answer_status=unavailable`（references 非空但无关）
- **THEN** 报告 `outcome=unable_to_assess`，无 Finding、无引用展示

### Requirement: 诚实性不变量 MUST 成立

传输失败/超时/无引用/无法回答 MUST 归为 `unable_to_assess` 或 `needs_input`，MUST NOT 归为 `no_findings`；失败原因 SHALL 通过 `reason_codes` 可区分；正常 Finding 的 `evidence_ids` SHALL 非空且 `chunk_id` 不丢失。

#### Scenario: 失败可区分

- **WHEN** 法规服务分别返回 `timeout` / `corpus_updating` / `unsupported`
- **THEN** 对应 `reason_codes` 分别为 `["timeout"]` / `["corpus_updating"]` / `["unsupported"]`

### Requirement: 未实现的 method MUST NOT 归为无问题

当请求含未实现的 `mode`（deterministic/semantic）时，系统 SHALL 记为 `unable_to_assess`，`reason_codes` 含 `not_implemented`。

#### Scenario: 未实现 method

- **WHEN** `modes=["deterministic"]`
- **THEN** 报告 `outcome=unable_to_assess`，coverage 含 `status=unable_to_assess`、`reason_codes=["not_implemented"]`
