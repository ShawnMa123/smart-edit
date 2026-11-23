# Proposal

## Why

参考原型已经有一套完整的工作区外壳与模块入口：顶部操作区（活动记录、组织与成员、通知待办、身份、开发对照）、58px 左侧导航、版本比较、活动记录、通知与实现状态对照。当前 `web/` 只有三栏内容区、英文顶栏和版本时间线，缺少这些入口，导致演示时“看起来不像同一个产品”，也让活动、通知和版本差异只能靠开发者口头解释。

这次 change 只补“视觉与交互外壳 + 可诚实实现的本地模块”。当前构建没有认证、组织成员服务、审批工作流，因此不能把 mock 的组织、成员、身份和审批数据直接伪装成真实能力；这些入口必须明确说明本构建不可用，同时保留原型的位置和交互形态。

## What Changes

- 增加 58px 桌面左侧导航（文档、版本、审批、评论、组织与成员、开发对照），窄屏下改为可横向切换的入口；活动项同时具有文字和颜色标记。
- 增加顶部操作区：`Activity`、`People`、`Inbox`、`Developer`，以及中性的 `Local demo session`；不展示姓名、头像或组织。
- 增加浏览器本地 **Activity Log**：记录真实发生的 UI 操作（导入、保存、capture/restore、audit run、knowledge ask、template apply、export attempt 等），最多保留 100 条，支持清空；不得生成假队友或假系统事件。
- 增加由活动记录派生的 **Notifications**：只展示真实本地事件及其未读状态，不展示虚构的待办任务或人员。
- 增加 **Version Compare**：选择两个已捕获版本，按投影文本逐段比较，显示新增/删除/变化；不生成 AI 摘要，不修改当前草稿。
- 增加只读 **Implementation Map**（开发对照）：列出 mock 模块、当前状态（可用/部分/不可用）和限制，不伪造 API 或后端能力。
- 对 `Organization & members`、`Identity`、`Approval` 增加**明确占位**：入口存在，打开后说明本构建没有认证/组织/审批服务、需要哪些后端能力，且不展示样例组织、成员或审批人。
- 保留英文界面和 `smart-edit` 品牌；不复制 HSBC 品牌、中文 chrome 或样例组织/当事人数据。
- **BREAKING**: 无后端或数据契约破坏；桌面/窄屏 shell 的布局与入口结构会变化。

## Capabilities

### New Capabilities

- `workspace-navigation`: 工作区导航壳层，包括左侧 rail、顶部操作区、窄屏入口、明确的不可用占位和只读实现状态入口。
- `workspace-activity`: 浏览器本地的活动记录与由其派生的通知；只记录真实 UI 事件，不伪造参与者或服务端审计。

### Modified Capabilities

- `document-editor`: 增加已捕获版本的比较能力，并保持版本历史不可变、比较不修改当前草稿。

## Impact

- 前端：`web/src/components/AppShell.tsx`、`web/src/App.tsx`、`web/src/components/` 新增导航/活动/通知/比较/占位组件，`web/src/styles.css` 增加 rail、action cluster、activity、notification 和 dialog 样式。
- 前端存储：新增浏览器本地 activity store；版本比较复用现有 `versionStore`，不新增服务端存储。
- 测试：新增组件单测和 e2e（rail、占位、activity、compare、English-only chrome），更新现有 `AppShell`/`VersionPanel` 相关断言。
- 不涉及：后端 API、数据库 schema、真实认证/组织/成员、审批工作流、评论、导出、语音、HSBC/中文品牌。