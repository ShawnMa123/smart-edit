# Spec Delta

## Purpose

定义 Automation 后台能力的访问边界：哪些角色能看到模块、能配置哪些资源、能向哪些下游发送，
以及部门级配置如何被限制在部门范围内；确保"银行后台运营能力"不会被前台申请人误用或越权调用。

## ADDED Requirements

### Requirement: 模块入口只对授权角色可见

系统 SHALL 依据 `automation.view` 权限决定 Automation 模块的可见性；无权限的角色 MUST NOT 看到
工作区 tab 或菜单入口，直接访问深链时 MUST 显示明确的"仅限 Bank Operations"说明，MUST NOT 静默空白或报错。

#### Scenario: 申请人看不到 Automation
- **WHEN** 当前用户只有 `document.read` / `document.edit` 等权限而没有 `automation.view`
- **THEN** 工作区不渲染 Automation tab 或菜单项
- **AND** 直接打开 Automation 深链时显示无权限说明而不是空白面板

#### Scenario: Bank Operations 能看到 Automation
- **WHEN** 当前用户拥有 `automation.view`
- **THEN** 工作区渲染 Automation 入口，并可进入只读视图

### Requirement: 查看、配置、发送、审计分别授权

后端 SHALL 对 `/automation/*` 的每次调用按能力判权：读取模板/连接器/映射/规则与预览需要
`automation.view`；创建或修改模板、连接器、映射、规则需要 `automation.configure`；
手动发送、重试、取消需要 `automation.dispatch`；回执与运行记录列表需要 `automation.audit`。
缺少相应权限时 MUST 返回 403，且 MUST NOT 产生任何写入或外发。

#### Scenario: 申请人不能配置连接器
- **WHEN** 没有 `automation.configure` 的用户调用 `POST /automation/connectors`
- **THEN** 服务端返回 403
- **AND** 数据库中没有新增连接器

#### Scenario: 合规角色只读
- **WHEN** 拥有 `automation.view` / `automation.audit` 但没有 `automation.dispatch` 的用户调用 `POST /automation/dispatches`
- **THEN** 服务端返回 403，且不产生下游 HTTP 调用

#### Scenario: Bank Operations 可以配置并发送
- **WHEN** 拥有 `automation.configure` 与 `automation.dispatch` 的用户依次保存连接器并手动发送
- **THEN** 两次调用都成功，并产生一条可查询的回执

### Requirement: 部门级配置限制在部门作用域内

模板、连接器与规则 SHALL 带 `department_id`（空值表示组织级）。`dept_admin` MUST 只能创建和修改
本部门的行，MUST NOT 修改组织级或其他部门的行；查询 MUST 返回组织级行与本部门（含其祖先部门）可见的行。

#### Scenario: 部门管理员管理本部门规则
- **WHEN** `dept_admin` 创建 `department_id` 为本部门的规则
- **THEN** 创建成功，并在本部门列表中可见

#### Scenario: 部门管理员不能修改组织级规则
- **WHEN** `dept_admin` 尝试修改 `department_id` 为空的组织级规则
- **THEN** 服务端拒绝该请求，组织级规则保持不变

#### Scenario: 其他部门的规则不可见
- **WHEN** `dept_admin` 查询规则列表
- **THEN** 结果只包含组织级行与本部门可见行，不包含其他部门专属的行

### Requirement: 组织级配置角色覆盖全部作用域

`bank_ops` 与 `org_admin` SHALL 能管理组织级与部门级配置；`org_admin` MUST 保留全部权限，
包括在任意部门范围内创建和修改。

#### Scenario: Bank Operations 配置组织级规则
- **WHEN** `bank_ops` 创建 `department_id` 为空的规则
- **THEN** 规则对所有部门可见，且只有 `bank_ops` / `org_admin` 能修改

#### Scenario: 组织管理员管理任意部门
- **WHEN** `org_admin` 修改任一部门的规则
- **THEN** 修改成功并写入审计

### Requirement: 既有 API Key scope 平滑过渡

既有 API Key 的 `automation.use` / `automation.apply` scope MUST 继续可用一个版本，但语义收窄为
只读与发送：`automation.use` 映射为 `automation.view`，`automation.apply` 映射为
`automation.dispatch`；二者 MUST NOT 授予 `automation.configure`。

#### Scenario: 旧 Key 仍可发送但不能改配置
- **WHEN** 持有 `automation.apply` scope 的 API Key 调用 `POST /automation/dispatches`
- **THEN** 调用按 `automation.dispatch` 语义被允许
- **AND** 同 Key 调用 `POST /automation/rules` 返回 403

### Requirement: 访问边界可审计且不破坏演示

权限与配置的每次变更 SHALL 写入审计（谁、何时、改了哪个资源）；本地演示身份
（`AUTH_MODE=fake`）MUST 保持 Automation 可用，不得因权限收口导致演示无法进入模块。

#### Scenario: 配置变更留痕
- **WHEN** 授权用户创建、修改或停用连接器/规则
- **THEN** 审计记录包含操作者、资源 id 与动作

#### Scenario: 演示模式仍可打开模块
- **WHEN** 服务以 fake identity 运行且未配置真实角色
- **THEN** 演示用户仍能打开 Automation 并使用配置能力