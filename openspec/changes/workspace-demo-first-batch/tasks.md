# Tasks

## 1. Demo mode and store foundation

- [x] 1.1 新增 `web/src/demo/demoMode.ts`：`readDemoMode`/`writeDemoMode`，默认 false，key `smart-edit:demo-mode`，storage 失败回退；验证：`demoMode.test.ts` 覆盖默认/持久化/失败。
- [x] 1.2 新增 `web/src/demo/demoData.ts`：定义 `DemoUserId`、`DemoUser`、`DemoOrg`、`DemoComment`、`DemoApproval`、`DemoActivity`、`DemoState`，并提供 `seedDemoState()`；验证：seed 包含四个用户、组织、两条评论、DRAFT 审批和 4–6 条 activity。
- [x] 1.3 新增 `web/src/demo/demoStore.ts`：独立 key `smart-edit:demo:collaboration:v1`，`read/write/reset/available`，schema 校验与损坏回退；验证：`demoStore.test.ts` 覆盖 seed/write/reset/schema mismatch，且真实 activity key 不变。
- [x] 1.4 在 `web/README.md` 记录 demo mode、demo store key、真实 store 隔离和 reset 边界；验证：README 可 grep 到 `smart-edit:demo-mode` 与 `not real authentication`。

## 2. Toggle, banner and top-bar identity

- [x] 2.1 修改 `EnvironmentStrip`：增加 `demoMode`、`onToggleDemo`、`onResetDemo`；demo on 时渲染固定 banner 与 Reset；off 时保持现有环境提示；验证：`AppShell.test.tsx` 覆盖 toggle 文案、banner、Reset 和 off 状态。
- [x] 2.2 扩展 `TopBar`：接受 `demoIdentity`，demo 模式显示 `Demo identity` 标记、姓名/组织、点击打开 identity dialog；off 时仍为 `Local demo session`；验证：`AppShell.test.tsx` 新增 demo identity 测试，原 no-identity 测试仍通过。
- [x] 2.3 在 `App.tsx` 接入 `demoMode`/`demoState` 初始化、toggle、reset、identity 弹窗与 topbar props；验证：App 集成测试默认 off、打开后 sample identity 出现、关闭后恢复 neutral session。

## 3. Identity and People demo

- [x] 3.1 新增 `DemoIdentityDialog`：列出四个 sample users、当前身份、角色/组织，切换写 demo store；标注 `Demo identity` 与“不影响真实 editor/lock/audit”；验证：组件测试覆盖切换、当前标记和无真实认证措辞。
- [x] 3.2 新增 `DemoPeopleDialog`：sample orgs、member rows、guest status、`Invite external counsel` / `Revoke guest` 本地动作；验证：组件测试覆盖目录、guest 状态、invite/revoke 与 `Simulated` 文案。
- [x] 3.3 在 `App.tsx` 的 `moduleBody` 为 People/Identity 增加 demo 分支，诚实模式仍走 `UnavailableModuleDialog`；验证：App 测试 demo on/off 两种分支。

## 4. Approval demo

- [x] 4.1 新增 `demoApproval.ts` 纯函数状态机：start、approve、reject、handoff，按 current user/step assignee 校验 self-approval；验证：单元测试覆盖 DRAFT→IN_REVIEW→APPROVED→HANDED_OFF、reject 和禁止自批。
- [x] 4.2 新增 `DemoApprovalDialog`：显示状态、step assignee、decision、`Simulated` receipt、Start/Approve/Reject/Confirm handoff；动作按 demo identity 权限 disabled；验证：组件测试覆盖两种身份与完整状态流。
- [x] 4.3 在 `App.tsx` 中 demo 模式 `Submit new version` 打开 Approval dialog（诚实模式保持现有 unavailable dialog）；验证：App 测试断言 demo on 进入 approval、demo off 仍显示 not available。

## 5. Comments demo

- [x] 5.1 新增 `DemoCommentsDialog`：seed threads、作者/角色/版本/quote/状态，新增评论使用当前 selection quote 与 current demo identity，Resolve 本地更新；验证：组件测试覆盖列表、带/不带 quote 新增、resolve、作者不可伪造。
- [x] 5.2 在 `App.tsx` 的 Comments header/rail 入口接入 demo 分支；诚实模式仍走 Comments 占位；验证：App 测试 demo on/off 两种入口。

## 6. Demo activity and Inbox

- [x] 6.1 新增 `DemoActivityPanel`（或 `ActivityPanel` sample 变体）：seeded demo events、sample actor、`Sample data` 标记、mark read；验证：组件测试覆盖 seed、计数、mark read、与真实 activity 文案区分。
- [x] 6.2 新增 `DemoNotificationPanel` 或在现有 NotificationPanel 增加 demo 输入：只从 demo activity 的 notifiable 派生，显示 sample actor，无真实 assignee；验证：组件测试覆盖过滤、未读、mark read。
- [x] 6.3 在 `App.tsx` demo 模式为 Activity/Inbox 选择 demo store，off 时恢复真实 `activityStore`；验证：App 集成测试两种模式计数/列表切换，真实 store 不变。

## 7. Integration verification and visual check

- [x] 7.1 更新/新增 e2e：toggle demo、banner、identity switch、People invite/revoke、Approval 状态流、Comments 新增/解决、Activity/Inbox sample、Reset、off 后恢复诚实占位；验证：`PW_CHANNEL=chrome npm --prefix web run e2e -- --project=desktop --project=narrow` 通过。
- [x] 7.2 运行 `npm --prefix web run typecheck && npm --prefix web run test && npm --prefix web run build`；验证：三条命令退出码为 0。
- [x] 7.3 在 1440×900、1024×800、412×915 检查 demo banner、identity、People/Approval/Comments/Activity、无横向滚动、English-only；验证：截图结果记录，未通过项不得勾选。

## Workflow follow-up

- Archive this change after the project's review requirements are satisfied.
- Confirm `workspace-demo-mode` and `workspace-collaboration-demo` purposes are carried into the main specs.
- 后续 change 再处理真实身份/组织/邀请、后端审批/评论、完整访客表单、HSBC/中文皮肤和其余模块。