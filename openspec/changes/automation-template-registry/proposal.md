# Proposal

## Why

Automation 工作台的模板只存在 `localStorage`（每浏览器一份、最多 20 个），下游发送是 mock
（`mockDownstreamSend.ts` 明确写着"no network request"）。这导致两个真实诉求做不到：

1. 用户导入/预置的模板无法**跨人共享**，也无法在换浏览器后继续用；
2. "识别模板里的变量并传给下游 API" 只能手工标记 `{{变量}}`，没有模型辅助，也没有真正的出站调用。

## What Changes

- 新增服务端模板注册表（workspace 作用域、落库）：`automation_templates` / `automation_connectors` /
  `automation_dispatches` 三张表（`HostStore` schema，创建即幂等）。
- `POST /automation/templates`：把当前草稿/导入文本存成服务器模板（同名自动升 patch 版本）。
- `POST /automation/templates/{id}/variables/suggest`：**确定性扫描 + 豆包**给出候选变量，
  每条带 verbatim quote；`use_llm=false` 可只用确定性路径；模型不可用时降级并给出 warning，不 500。
- `PUT /automation/templates/{id}/variables`：用户确认后的变量集合才落库（建议从不自动保存）。
- `POST /automation/templates/{id}/prepare`：把已确认变量绑定到当前草稿（`label: value`），
  缺值如实列出 `missing_required`，不猜。
- `POST /automation/connectors`：登记下游（base_url/path/auth），密钥只存**环境变量名**。
- `POST /automation/dispatches`：渲染 payload 并做一次真实 HTTP 调用；主机白名单 + https
  （或显式允许 http）+ 超时 + 幂等键；请求/响应（截断）/耗时/状态全部落库，形成可审计回执。
- 前端 Automation 增加第 4 个区域 **Server & Downstream**：存模板 → AI 找变量 → 确认 → 从草稿取值 →
  选连接器 → 真实发送并展示回执/历史。其它三个区域保持浏览器本地（并明确标注 simulate/mock）。
- 新增 `scripts/echo_downstream.py`：本地回显服务，用于演示真实 dispatch 的 200 回执。

## Capabilities

### New Capabilities

- `automation-template-registry`：模板/变量的服务端持久化、AI 变量识别（证据约束）、
  以及 allow-list + 环境变量密钥的下游 dispatch 与回执审计。

### Modified Capabilities

<!-- 无：现有 automation proposals/apply 流程未改动；本 change 只新增 registry 与 dispatch。 -->

## Impact

- 后端：`app/automation/{registry,registry_schemas}.py`、`app/documents/store.py`（3 张表）、
  `app/api/automation.py`（11 条新路由）、`app/api/main.py`（注入 registry）。
- 前端：`web/src/api/automationRegistry.ts`、`web/src/components/AutomationServerPanel.tsx`、
  `AutomationWorkbench.tsx`（新增区域与边界文案）、`AssistantPanel.tsx`（状态标签）。
- 测试：`tests/test_automation_registry.py`（11 条）、`AutomationServerPanel.test.tsx`（3 条）、
  `automationRegistry.test.ts`（5 条）。
- 配置：`SMART_EDIT_AUTOMATION_ALLOWED_HOSTS`、`SMART_EDIT_AUTOMATION_ALLOW_HTTP`、连接器 `secret_env`。
- 安全：密钥不入库、不回显；未白名单主机与缺密钥是显式拒绝（403/409），并记录 refused 回执。