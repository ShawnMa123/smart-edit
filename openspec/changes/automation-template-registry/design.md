# Design

## Context

- 工作台（`AutomationWorkbench`）的三个区域是本地的：`templateStore`（localStorage，上限 20）、
  `downstreamSystemStore`（本地）、`mockDownstreamSend`（模拟 200/500，明确不发网络）。
- 服务端已有 `/automation` 的 runs/proposals（草稿操作提案），但没有"模板 → 变量 → 下游"的注册表。
- 可复用件：`HostStore`（SQLite、事务、schema 幂等）、`DoubaoGateway.compose_json()`（结构化 JSON）、
  `DocumentService.document_view()`（授权后的草稿读取）、`HostError`（错误契约）。

## Decisions

### D1 · 模板与变量落库，但**建议不落库**

`automation_templates` 只存模板文本与**已确认**的 `variables_json`。`suggest` 是只读计算，
返回 `suggested_by ∈ {deterministic,llm,merged}` 与 `warnings`，不改库；用户点"确认"才走
`PUT .../variables`。这样"模型提了什么"和"人确认了什么"在数据上可区分。

### D2 · 确定性优先，模型补充；两者都要证据

- 确定性：`{{label}}`/`[[label]]` 占位符、`____` 空白、`Label: value` 行（value 像金额/日期/币种/编号/短专名）。
  这是无模型也能用的路径，也可测试。
- 豆包：`compose_json` + 固定 prompt（"只列每笔交易会变的字段；quote 必须逐字来自模板"）。
  返回后逐条校验：`quote` 必须能在模板里定位（空白容错），定位不到 → `quote=None` + warning
  `quote_not_found:<label>`；未知 `value_type` 归一为 `string`；上限 30，去重。
- 合并：按 `key` 合并，确定性证据优先，模型只补类型/必填；`suggested_by` 反映是否用了模型。
- 模型不可用/报错：降级为确定性结果 + `llm_unavailable` / `llm_error:<Type>`，接口不 500。

### D3 · 变量绑定只做"label → value"，不猜

`prepare` 在草稿文本里找 `label: value`（以及 `label_name` ↔ `label name`、长 token 回退，
例如 `applicant_name` ↔ `Applicant:`）。找不到就是 `source="missing"`，必填缺失进 `missing_required`。
payload 只包含**真实找到或用户补填**的值。

### D4 · 下游调用：白名单 + 环境变量密钥 + 幂等 + 回执

- 主机必须在 `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS`（逗号分隔；空 = 全拒）；默认只允许 https，
  除非 `SMART_EDIT_AUTOMATION_ALLOW_HTTP=1`（仅内网/演示）。
- 连接器只存 `secret_env`（环境变量名），值不落库、不回显、不写回执；`secret_configured` 只表示"环境里有没有"。
- `Idempotency-Key`（请求体或客户端传入）命中同一 dispatch 时直接返回原回执，不重复调用。
- 每次调用（含被拒绝的）都写 `automation_dispatches`：status / status_code / latency_ms /
  请求 payload / 响应截断(<=2000) / error_code。
- 拒绝码：`host_not_allowed` / `tls_required`（403）、`secret_missing`（409）、`invalid_target`（400）。

### D5 · 权限沿用既有 capability

读（列表/建议/绑定/回执）用 `read`；写（建模板/存变量/建连接器/dispatch）用 `apply`。
与 `run_service`（`read`）和 proposals（`apply`）的口径一致，不新增权限名。

### D6 · 请求体按下游 OpenAPI 规范组装（不是自定义信封）

- 连接器 SHALL 可以附带 `spec`（OpenAPI 3.x JSON，≤512 KB）与 `operation`（`"POST /trade/applications"`）；
  有 spec 时，**方法名与 path 由 spec 决定**（请求里显式给的非默认 path 才覆盖），避免"spec 说 PUT、实际发 POST"。
- 解析是刻意的小子集：本地 `$ref`、object → 点号标量路径（`beneficiary.name`）；
  `oneOf`/`anyOf`、数组、外部 `$ref`、循环引用 SHALL 标为 unsupported 并在 `spec_warnings` 里说明，
  MUST NOT 猜测或静默展开。
- `prepare`（带 `connector_id`）返回 `request_body` = 按 spec 组装的真实请求体、
  `body_mapping`（`{字段路径: 变量 key}`）、`body_issues`（missing/invalid/unsupported）与 `unmapped_required`。
- 组装规则：未映射的可选字段直接省略；必填缺失或类型不合法（enum / number / integer / boolean）
  SHALL 成为 issue；数值字段接受文档里的写法（`USD 750,000.00` → `750000.0`）。
- 映射未配置时 SHALL 按变量 label 自动建议（generic 叶子如 `name`/`date` 回退到父段）；
  一旦 `PUT /connectors/{id}/mapping` 保存过，就**完全按保存的映射发送**（清空也是决定，不再自动补）。
- `dispatch`：有 spec 时发送 `request_body` 本身；body 不满足 spec → `409 missing_required_body`
  并写 `refused` 回执（含字段清单），MUST NOT 用"差不多"的 body 打过去。
  没有 spec 的连接器仍发旧的扁平 `{template, values}` 信封，保证向后兼容。

## Risks / Trade-offs

- 确定性启发式会把"Governing Rules: URDG 758"这类固定字段也列为候选：它是**候选**，由用户取消勾选；
  prompt 里也要求模型不要列固定字段。
- 变量上限 40、模板 200k 字符、响应截断 2000 字符：超出即拒绝或截断并在回执里体现。
- 白名单允许 HTTP 是演示便利：生产应只开 https 且把主机收窄到具体下游域名。

## Migration / Rollout

1. 三张表在 `HostStore` schema 里以 `CREATE TABLE IF NOT EXISTS` 建好，旧库启动即自动补表，无需版本迁移。
2. `.env` 增加 `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS`（默认空 = fail closed）；演示环境可配 `127.0.0.1` +
   `..._ALLOW_HTTP=1`，配合 `scripts/echo_downstream.py`。
3. 前端只新增区域，不改既有三个区域的行为；回滚只需移除该区域与环境变量。