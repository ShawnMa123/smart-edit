# Tasks

## 1. 存储（`app/documents/store.py`）

- [x] 1.1 `automation_templates`（workspace 作用域、name+version 唯一、variables_json、variables_source）
- [x] 1.2 `automation_connectors`（base_url/path/method/auth_kind/secret_env/timeout）
- [x] 1.3 `automation_dispatches`（status/status_code/latency/request/response/error/idempotency）
- [x] 1.4 建表放在既有 schema 中（`IF NOT EXISTS`，旧库启动自动补表）

## 2. 服务（`app/automation/registry.py`）

- [x] 2.1 模板 CRUD + 同名 patch 版本递增
- [x] 2.2 确定性变量识别（占位符 / 空白 / `Label: value`）
- [x] 2.3 豆包建议（固定 prompt + verbatim quote 校验 + 去重 + 上限）
- [x] 2.4 合并策略（确定性证据优先；模型补类型/必填）与降级 warning
- [x] 2.5 确认后保存变量（唯一 key、上限 40）
- [x] 2.6 `prepare`：label→value 绑定（含 `label_name` ↔ `Label:` 回退）、`missing_required`
- [x] 2.7 连接器创建（URL 校验、凭据不得出现在 URL、auth 必填项）
- [x] 2.8 dispatch：白名单、https/显式 http、环境变量密钥、超时、幂等、回执落库

## 3. HTTP（`app/api/automation.py`、`app/api/main.py`）

- [x] 3.1 `GET/POST /automation/templates`、`GET /automation/templates/{id}`
- [x] 3.2 `POST /automation/templates/{id}/variables/suggest`（`?use_llm=false`）
- [x] 3.3 `PUT /automation/templates/{id}/variables`
- [x] 3.4 `POST /automation/templates/{id}/prepare`
- [x] 3.5 `GET/POST /automation/connectors`
- [x] 3.6 `GET/POST /automation/dispatches`
- [x] 3.7 `create_app` 注入 registry（复用豆包 gateway 与 approved 标记）

## 4. 前端

- [x] 4.1 `web/src/api/automationRegistry.ts`（类型 + 9 个方法 + 错误契约）
- [x] 4.2 `AutomationServerPanel`：模板保存/选择 → AI 变量（可取消勾选）→ 确认 → 取值 → 发送 → 回执/历史
- [x] 4.3 `AutomationWorkbench` 增加 `Server & Downstream` 区域（键盘导航随之更新）
- [x] 4.4 边界文案改为"浏览器本地三区是模拟；Server 区是真实"；tab 状态改为 `Server + fixture`

## 5. 演示与验证

- [x] 5.1 `scripts/echo_downstream.py`（127.0.0.1 回显，只报 key 是否存在，不回显密钥）
- [x] 5.2 线上实测：模板 → merged 建议（豆包）→ 存变量 → 从 `demo-document` 取值 → 真实 200 回执（15ms）
- [x] 5.3 拒绝路径：未白名单 403 / 缺密钥 409 / 非 https 403，且都留 refused 回执
- [x] 5.4 `pytest tests`：867 passed；前端 553 passed；`npm typecheck` 通过

## 6. 后续（未包含）

- [ ] 6.1 模板版本对比与回滚（当前每次保存升 patch，旧版本仍可读）
- [ ] 6.2 连接器编辑/停用 UI（表已支持 `disabled_at`，API 只做了创建）
- [ ] 6.3 变量级校验（金额精度、日期格式）与 `value_type` 驱动的 payload 类型转换
- [ ] 6.4 多实例部署时把 registry/dispatch 迁到 PG（表结构已按可迁移形状设计）
- [ ] 6.5 下游失败重试/退避与死信（当前只记录 failed + error_code）
## 7. OpenAPI 驱动的请求体（D6）

- [x] 7.1 `app/automation/openapi.py`：OpenAPI 3.x 子集解析（本地 `$ref`、点号标量路径、unsupported 报告）
- [x] 7.2 连接器携带 `spec_json` / `operation` / `body_map_json` / `body_map_configured`（schema v5→v6 守卫迁移）
- [x] 7.3 `prepare(connector_id)` 返回 `request_body` / `body_mapping` / `body_issues` / `unmapped_required`
- [x] 7.4 `PUT /automation/connectors/{id}/mapping` 持久化字段→变量映射（清空也是决定）
- [x] 7.5 dispatch 发送 spec body；不满足必填 → 409 `missing_required_body` + refused 回执
- [x] 7.6 前端：粘贴 spec → 解析/选操作 → 字段映射下拉 → body 预览 + 缺字段时禁用发送
- [x] 7.7 测试：解析/组装/映射/拒绝/兼容旧信封（后端 22 条 registry 用例 + 前端 12 条）
- [x] 7.8 面板引导：`automation/flow.ts` 计算"下一步"，`Step n/m` + `Show me` + 进度点 + `Target` 行
- [x] 7.9 合并 `Review & send` 卡片：映射、取值、请求体预览、`Send`、回执在同一块；`Send` 被禁用时给出原因
- [x] 7.10 连接器原地编辑：`PUT /connectors/{id}` + `GET /connectors/{id}/spec`（换 spec 重置映射并提示）
- [x] 7.11 连接器停用：`DELETE /connectors/{id}` 软删除（回执保留、dispatch 404）+ 面板二次确认
- [x] 7.12 单步模式（`Step-by-step`，Back/Next）与模板名取自草稿首行（同名提示新版本）
- [x] 7.13 模板生命周期：PUT / duplicate / DELETE 三个端点 + 面板 Rename / Duplicate / Delete
- [x] 7.14 模板 → 新文档：POST .../apply 渲染三种占位写法 + `Use as new document` 按钮
- [x] 7.15 手工字段表：`fields` 与 spec 互斥、共用映射/校验/组包（schema_kind=fields）
- [x] 7.16 dry-run：`POST /dispatches/preview`（打码请求头、不发送、不写回执）+ 面板 `Preview request`
- [x] 7.17 值回填草稿：`POST /templates/{id}/write-back`（锁 + expected_revision、只改文本节点、stale → 412）
- [x] 7.18 映射按 (template, connector) 隔离：`automation_mappings` 表 + `GET /mappings` + 面板按配对读取
- [x] 7.19 回执可复现：`target` + `sent_body` 落库，面板 `Copy as curl` / `Download payload` / `Send again` + 状态过滤
- [x] 7.20 信息架构收敛：四个 tab → `Automate`（默认，真实链路）+ `Sandbox`（本地演练，三段式），并移除沙箱 mock 发送
- [x] 7.21 无状态契约助手：`POST /automation/spec/parse` 与 `POST /automation/spec/build`（与 dispatch 共用同一解析/组包）
- [x] 7.22 沙箱预览改调 7.21 的两个端点，删除前端 `openapi.ts` / `openapiPayload.ts`（−479 行实现、−314 行测试）

## 8. 规范支持的后续项（未做）

- [ ] 8.1 Swagger 2.0 / YAML：目前只接受 OpenAPI 3.x **JSON**，其它格式给出明确错误（不猜）
- [ ] 8.2 按 URL 拉取 spec（需要走主机白名单，避免 SSRF；当前只支持粘贴）
- [ ] 8.3 数组 / `oneOf` / `anyOf` 的映射（当前标为 unsupported 并跳过）
- [ ] 8.4 按 spec 自动生成连接器（`servers[0]` → base_url），减少手填
