# Proposal

## Why

默认诚实模式下，People、Approval、Comments 等入口会显示“not available”说明，无法展示参考原型的完整协作观感。现在没有认证/组织/审批/评论后端，因此先引入一个**显式 Demo data 模式**：默认关闭，打开后用浏览器本地 sample data 填充第一批四个模块，让界面看起来像真实产品，同时不伪装成真实登录或真实审批。

## What Changes

- 在 environment strip 增加 `Demo data` 开关，默认 off，状态持久化；打开时显示固定 banner：
  `Demo data — sample users, organisations and approvals; not real authentication or workflow.`
- 新增浏览器本地 demo data 层，独立于真实 activity/store：
  - Demo identity：Chen Rui（Applicant）、Emma Wong（Bank operations）、Daniel Lee（Compliance）、Lin Yan（External counsel / guest）。
  - Demo organisations：Alpha Tech Ltd.、HSBC Trade Operations、HSBC Compliance、Harbour Legal Partners。
  - Demo state：comments、approval、activity、inbox 派生数据、当前 demo identity。
- Demo 模式打开后：
  - 顶栏显示带 `Demo identity` 标记的身份切换器；关闭后恢复 `Local demo session`。
  - People 入口显示 sample 组织/成员/外部访客，并支持本地 demo 邀请/撤权。
  - Approval 入口显示样例审批状态机（DRAFT → IN_REVIEW → APPROVED/HANDED_OFF），按当前 demo 身份控制批准/退回；回执明确标 `Simulated`。
  - Comments 入口显示样例线程、选区引用和 resolve；新评论只写本地 demo store。
  - Activity 入口显示 seeded sample events，并接收 demo 操作产生的新事件；Inbox 由 demo activity 派生。
  - 编辑器 footer 的 `Submit new version` 在 demo mode 下进入 sample approval；诚实模式仍保持“not available” dialog。
- Demo 模式关闭时恢复当前诚实行为：无 sample identity、People/Approval/Comments 仍为明确占位，Activity 仍只记录真实本地事件。
- Demo banner 提供 `Reset demo data`，清空 sample state 但保留真实 activity/version/draft。
- **BREAKING**: 无后端或数据契约破坏；新增显式 demo mode 与 sample data 层。

## Capabilities

### New Capabilities

- `workspace-demo-mode`: 显式 Demo data 开关、持久 banner、demo store 隔离/重置，以及关闭后回到诚实模式。
- `workspace-collaboration-demo`: Demo 模式下的 sample identity/People、Approval、Comments 与 demo activity/inbox 行为；demo identity/activity 只在显式 demo mode 下生效，诚实模式规则不变。

### Modified Capabilities

无。

## Impact

- 前端：`App.tsx`、`AppShell.tsx`、`UnavailableModuleDialog` 的 demo 分支、新增 `web/src/demo/` 数据层与 People/Approval/Comments 组件、`styles.css`、`web/README.md`。
- 前端存储：新增 demo mode key 与分离的 demo collaboration/activity store；真实 activity/version/draft 不受影响。
- 测试：新增 demo mode 组件/集成/e2e；默认诚实模式的 no-identity/real-activity 断言保持不变。
- 不涉及：HSBC/中文视觉皮肤、真实认证/组织/邀请服务、后端审批/评论 API、导出、语音、完整 Reviewer/审批治理。