# Spec Delta

## Purpose

规定服务端的自动化模板注册表与下游 dispatch：模板与**已确认**变量持久化、确定性 + 豆包的变量建议
（必须带 verbatim quote）、按 label 从草稿取值、以及 allow-list + 环境变量密钥的真实 HTTP 调用与回执审计。

## ADDED Requirements

### Requirement: 模板 MUST 持久化且按 workspace 隔离

系统 SHALL 把模板文本、版本、来源与已确认变量存进数据库，并按 `workspace_id` 隔离读取与写入；
同名重复保存 SHALL 生成新版本而不是覆盖已有版本。

#### Scenario: 同名再存生成新版本

- **WHEN** 同一 workspace 用相同 `name` 再保存一次模板
- **THEN** 新行 `version` 的 patch 号加一（如 `1.0.0` → `1.0.1`），旧版本仍可读

#### Scenario: 跨 workspace 不可见

- **WHEN** 另一个 workspace 读取该 `template_id`
- **THEN** 返回 404（不泄露存在性）

### Requirement: 变量建议 MUST 带原文证据，且 MUST NOT 自动保存

`suggest` SHALL 返回确定性候选与（可用时）豆包候选；每条 SHALL 带 `quote`，
`quote` 必须能在模板文本中定位，定位不到时 SHALL 置空并给出 `quote_not_found:<label>` warning；
模型不可用/失败 SHALL 降级为确定性结果并给出 `llm_unavailable` / `llm_error:<Type>`，MUST NOT 500；
建议结果 MUST NOT 写入模板，只有 `PUT .../variables` 才落库。

#### Scenario: 模型乱造 quote 被降级

- **WHEN** 模型返回的 `quote` 不在模板里
- **THEN** 该变量的 `quote` 为空、`source=llm`、`warnings` 含 `quote_not_found:<label>`，接口仍 200

#### Scenario: 没有模型也能用

- **WHEN** `?use_llm=false` 或模型未配置
- **THEN** 返回 `suggested_by=deterministic` 的变量（占位符/空白/`Label: value`），并（未配置时）带 `llm_unavailable`

### Requirement: 取值 MUST 只匹配 label，不猜值

`prepare` SHALL 在草稿文本里找 `label: value`（支持 `label_name` ↔ `label name` 与长 token 回退）；
找不到 SHALL 记 `source=missing`，必填变量缺失 SHALL 出现在 `missing_required`；payload MUST 只含真实找到的值。

#### Scenario: 占位符变量绑定到短 label

- **WHEN** 变量是 `applicant_name`，草稿写的是 `Applicant: Gamma Holdings Ltd`
- **THEN** `values["applicant_name"].value == "Gamma Holdings Ltd"` 且 `source=document`

#### Scenario: 缺值如实报告

- **WHEN** 草稿没有金额行
- **THEN** `values["amount"].source == "missing"`，`amount` 在 `missing_required` 中

### Requirement: Dispatch MUST 只打白名单主机，并用环境变量取密钥

dispatch SHALL 只允许 `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS` 中的主机；默认 SHALL 只允许 https，
除非 `SMART_EDIT_AUTOMATION_ALLOW_HTTP=1`；密钥 SHALL 从 `secret_env` 指定的环境变量读取，
MUST NOT 存入数据库、MUST NOT 出现在响应/回执；每次调用（含拒绝）SHALL 落一条回执。

#### Scenario: 未白名单拒绝

- **WHEN** 连接器主机不在白名单
- **THEN** 返回 403 `host_not_allowed`，下游未收到请求，回执 `status=refused`

#### Scenario: 缺密钥拒绝

- **WHEN** `auth_kind=bearer` 且 `secret_env` 指向的环境变量为空
- **THEN** 返回 409 `secret_missing`，下游未收到请求

#### Scenario: 成功回执包含耗时与响应

- **WHEN** 下游返回 2xx
- **THEN** 回执 `status=succeeded`、`status_code`、`latency_ms` 与响应截断（≤2000 字符）均被记录并可查询

### Requirement: Dispatch MUST 幂等

同一 workspace + `idempotency_key` 的重复 dispatch SHALL 返回同一回执，MUST NOT 触发第二次 HTTP 调用。

#### Scenario: 重复键只发一次

- **WHEN** 用相同 `idempotency_key` 调用两次
- **THEN** 两次返回同一 `dispatch_id`，下游只收到一次请求

### Requirement: 请求体 MUST 按下游 OpenAPI 规范组装

连接器 SHALL 可附带 OpenAPI 3.x JSON 与 `operation`。有 spec 时，`prepare`（带 `connector_id`）SHALL 返回
`request_body`（按 spec 组装的真实请求体，含嵌套字段）、`body_mapping`、`body_issues` 与 `unmapped_required`；
`dispatch` SHALL 发送该 body 而不是自定义信封；必填字段缺失或类型不符 SHALL 返回 409 `missing_required_body`
并留下 `refused` 回执。未映射的可选字段 MUST NOT 被发送；无法解析的 schema（`oneOf`/数组/外部 `$ref`/循环）
SHALL 标为 unsupported 并在 `spec_warnings` 中说明。

#### Scenario: 嵌套字段与数值类型按 spec 生成

- **WHEN** spec 的 requestBody 要求 `amount: number` 与 `beneficiary.name: string`，草稿里是 `Amount: USD 250,000.00`
- **THEN** 发送的 body 为 `{"amount": 250000.0, "beneficiary": {"name": "…"}}`（不是 `USD 250,000.00` 字符串）

#### Scenario: 必填缺失时拒绝发送

- **WHEN** 某个 required 字段没有映射或值为空
- **THEN** 返回 409 `missing_required_body`（附字段清单），下游未收到请求，回执 `status=refused`

#### Scenario: 保存过的映射（含清空）被遵守

- **WHEN** 用户通过 `PUT /automation/connectors/{id}/mapping` 保存了映射（哪怕是空对象）
- **THEN** 之后按保存内容发送，MUST NOT 用自动建议覆盖用户的决定

### Requirement: 连接器 MUST 可原地编辑、可停用

系统 SHALL 支持 `PUT /automation/connectors/{id}` 修改名称、host、path、认证与 spec/operation；
替换 spec 或 operation 时 SHALL 重置该连接器的字段映射（旧路径属于旧契约）并给出可见提示；
`DELETE /automation/connectors/{id}` SHALL 软删除（`disabled_at`），列表不再返回、dispatch SHALL 404，
历史回执 MUST 保留。`GET /automation/connectors/{id}/spec` SHALL 返回已存文档，供编辑器回填。

#### Scenario: 改名不影响映射

- **WHEN** 只改 `name` / `timeout_seconds`
- **THEN** 连接器更新成功，`body_map` 与 `operation` 保持不变

#### Scenario: 换 spec 重置映射

- **WHEN** `PUT` 带上新的 OpenAPI 文档
- **THEN** `operation` 取新文档的默认操作、`path` 跟随新 operation，`body_map` 清空（回到自动建议）

#### Scenario: 停用后不能再发

- **WHEN** 连接器被 `DELETE`
- **THEN** 列表中不再出现，dispatch 返回 404，且下游未收到请求

### Requirement: 模板 MUST 可改名、复制、删除，并能渲染成新文档

系统 SHALL 支持 `PUT /automation/templates/{id}`（改名，`(name, version)` 冲突 SHALL 409 `name_taken`）、
`POST .../duplicate`（复制文本与已确认变量到新名字）、`DELETE /automation/templates/{id}`
（删除单个版本；dispatch 回执 MUST 保留自己的快照）。
`POST .../apply` SHALL 用已确认变量渲染模板为**新文档**：支持 `{{label}}`、`[[label]]` 与 `Label: value`
三种写法；没有值的必填变量 MUST 出现在 `missing` 且 MUST NOT 被编造。

#### Scenario: 改名冲突被拒绝

- **WHEN** 把模板改成一个已存在同名同版本的模板名
- **THEN** 返回 409 `name_taken`，名字不变

#### Scenario: 复制带走变量

- **WHEN** 对含 6 个已确认变量的模板执行 duplicate
- **THEN** 新模板 `variables` 同样是 6 条，`source_note` 记录来源

#### Scenario: 渲染生成新文档

- **WHEN** apply 时给了 `amount` / `applicant` 的值
- **THEN** 新文档文本里 `Amount:` 与 `{{applicant}}` 都变成对应值，`filled` 含这两个 key，
  未给值的必填变量出现在 `missing`

### Requirement: 无 OpenAPI 的下游 MUST 可用字段表，且 MUST 支持 dry-run 预览

连接器 SHALL 可声明 `fields: [{path, type, required}]`（与 `spec` 互斥），其映射、校验与组包 MUST 复用
OpenAPI 路径的同一实现（`schema_kind=fields`）；字段路径 MUST 为点号名字，重复路径或非法类型 SHALL 400。
`POST /automation/dispatches/preview` SHALL 返回 `url` / `method` / 请求头（密钥值 MUST 打码）/
`body` / `issues` / `refusal`，且 MUST NOT 发起 HTTP、MUST NOT 写回执。

#### Scenario: 字段表生成同样的嵌套请求体

- **WHEN** 连接器字段为 `amount: number *` 与 `beneficiary.name: string *`，值为 `USD 750,000.00`
- **THEN** 请求体为 `{"amount": 750000.0, "beneficiary": {"name": "…"}}`

#### Scenario: 预览不产生副作用

- **WHEN** 调用 preview
- **THEN** 返回目标 URL 与打码后的请求头，下游未收到请求，`GET /dispatches` 仍为空

### Requirement: 变量值 MUST 可回填到当前草稿（锁 + 乐观版本）

`POST /automation/templates/{id}/write-back` SHALL 在接受 `document_id`、`draft_id`、`lock_id`、
`fencing_token`、`expected_revision` 与 `values` 后，把值写入**当前草稿**：
只修改文本节点（结构、mark、表格 MUST 保留）；写入 MUST 经过编辑锁校验与 `expected_revision`
（不匹配 SHALL `412 stale_draft`）；草稿中不存在的标签 SHALL 出现在 `skipped` 而 MUST NOT 报错；
没有任何匹配时 MUST NOT 产生新版本。

#### Scenario: 只替换文本节点

- **WHEN** 草稿是带标题/加粗的 rich 文档，值为 `USD 250,000.00`
- **THEN** 该行文本被替换，标题层级、加粗与其它节点保持原样，`revision` 加一

#### Scenario: 版本冲突不覆盖

- **WHEN** `expected_revision` 落后于服务端
- **THEN** 返回 412 `stale_draft`（附 `current_revision`），草稿内容不变

#### Scenario: 标签缺失只报告

- **WHEN** 传入的某个变量在草稿里根本没有对应标签
- **THEN** 该 key 出现在 `skipped`，其余值正常写入

### Requirement: 字段映射 MUST 按 (template, connector) 隔离

`PUT /automation/connectors/{id}/mapping` 带 `template_id` 时 SHALL 把映射存到
`automation_mappings(template_id, connector_id)`；不同模板对同一连接器的映射 MUST NOT 互相覆盖。
`GET /automation/mappings?template_id=&connector_id=` SHALL 返回 `body_map` 与 `configured`；
`configured=false` 时 `prepare`/`dispatch` SHALL 按变量标签自动建议。
不带 `template_id` 的旧映射 SHALL 继续作为回退生效（向后兼容）。
配对映射即使为空对象也 MUST 视为"已配置"（不自动补建议）。

#### Scenario: 一个连接器服务两个模板

- **WHEN** 模板 A 映射 `amount→amount`，模板 B 映射 `beneficiary.name→applicant`
- **THEN** 两个模板各自 `prepare` 得到自己的 `body_mapping`，互不影响

#### Scenario: 未配置时给建议

- **WHEN** 该配对没有映射记录
- **THEN** `GET /mappings` 返回 `configured=false`，`prepare` 返回按标签匹配的建议映射

#### Scenario: 空映射不被建议覆盖

- **WHEN** 该配对保存了空对象
- **THEN** `prepare` 的 `body_mapping` 为空、必填字段进入 `unmapped_required`

### Requirement: 回执 MUST 足以审计与重放

每份 dispatch 回执 SHALL 记录 `target`（url / method / schema_kind）与 `sent_body`（实际发出的 body 副本，
MUST NOT 改变真正发出的内容），且 MUST NOT 包含密钥。面板 SHALL 提供 `Copy as curl`（鉴权头写成环境变量
占位）、`Download payload` 与 `Send again`；历史列表 SHALL 支持按 `succeeded / failed / refused` 过滤。

#### Scenario: curl 里没有密钥

- **WHEN** 对带 `X-Api-Key` 的连接器点 `Copy as curl`
- **THEN** 命令里是 `X-Api-Key: $SMART_EDIT_DOWNSTREAM_TOKEN`，不含真实 token

#### Scenario: 回执能重放

- **WHEN** 读取任意成功回执
- **THEN** `request.target.url` 与 `request.sent_body` 存在，`sent_body` 与下游收到的一致

#### Scenario: 历史过滤

- **WHEN** 选择 `Refused`
- **THEN** 列表只显示 `refused` 的回执

### Requirement: 面板 MUST 区分"真实链路"与"本地沙箱"

自动化工作台 SHALL 只有两个顶层区域：`Automate`（默认打开，全部走服务端）与 `Sandbox`
（浏览器本地，MUST NOT 发请求也不得显示"已发送"的假回执）。沙箱内 SHALL 以分段控件区分
模板 / 变量 / 载荷预览，并在顶部说明"不会离开浏览器"；真实发送只允许出现在 `Automate`。

#### Scenario: 默认进入真实链路

- **WHEN** 打开 Automation 标签
- **THEN** `Automate` 处于选中状态，`Sandbox` 的分段控件不可见

#### Scenario: 沙箱不发送

- **WHEN** 在 Sandbox 里构建载荷
- **THEN** 只提供预览与下载，没有发送按钮，也没有 mock 回执

### Requirement: 权限 MUST 区分读写

读取（模板列表/详情、建议、绑定、回执）SHALL 需要 `read` capability；
写入（建模板、存变量、建连接器、dispatch）SHALL 需要 `apply` capability。

#### Scenario: 只读主体不能写

- **WHEN** 只有 `read` 的主体创建模板
- **THEN** 返回 403 `capability_denied`