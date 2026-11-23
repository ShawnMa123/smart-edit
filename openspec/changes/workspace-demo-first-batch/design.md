# Design

## Context

见 `proposal.md` 的 Why。当前实现的关键约束：

- `App.tsx` 默认渲染诚实模式：`TopBar` 显示 `Local demo session`，`People`/`Approval`/`Comments` 打开 `UnavailableModuleDialog`，Activity 只读真实 `activityStore`。
- `activityStore` 按 `smart-edit:activity:<documentId>` 持久化，明确“不是 server audit”；真实 activity 不应被 sample data 污染。
- `workspace-shell` 的 no-identity 规则和 `workspace-activity` 的“不伪造 sender/assignee”规则必须在诚实模式继续成立。
- 现有 `WorkspaceDialog`、`WorkspaceRail`、`TopBar`、`ActivityPanel`/`NotificationPanel` 可以复用外形。
- 编辑器/锁/审计的真实行为不在本 change 内；demo identity 只影响 sample collaboration，不改变真实 principal。

## Goals / Non-Goals

**Goals:**

- 默认 off；打开 `Demo data` 后，第一批四类模块呈现完整的 sample 数据与交互。
- Demo 数据与真实 activity/draft/version 完全隔离，关闭后恢复诚实模式。
- 用固定 banner、`Demo identity`、`Simulated` 标签把 sample 边界说清楚。
- 保持英文 shell 与 smart-edit 品牌；不引入 HSBC/中文皮肤。

**Non-Goals:**

- 不实现真实认证/组织/邀请、后端审批/评论、真实 ACL。
- 不实现完整访客邀请表单、审批治理、导出、语音或字段确认。
- 不改变真实编辑器、锁、审计、知识助手的 API 或状态机。
- 不把 demo sample events 混进真实 activity log。

## Decisions

### D1 `Demo data` 是显式、持久、默认 off 的开关

新增 `web/src/demo/demoMode.ts`：

```ts
const DEMO_MODE_KEY = 'smart-edit:demo-mode';

readDemoMode(): boolean;      // missing/failed -> false
writeDemoMode(enabled: boolean): void;
```

- `App.tsx` 初始化 `demoMode` 从该 key 读取；toggle 写入并更新 state。
- 开关放在 `EnvironmentStrip` 右侧，文案 `Demo data`；打开时同一 band 显示：
  `Demo data — sample users, organisations and approvals; not real authentication or workflow.`
- 另提供 `Reset demo data` 按钮（banner 内），只在 demo 模式显示。
- 存储不可用时 toggle 仍可工作，但 banner 提示 `Demo data is session-only in this browser.`；不假装已持久化。

替代方案：把 toggle 放 topbar。topbar 已有 Activity/People/Inbox/Developer/session，继续加会过密；environment strip 更适合“全局模式”。

### D2 Demo 状态是一个独立的、版本化 store

新增 `web/src/demo/demoStore.ts` 与 `demoData.ts`：

```ts
interface DemoState {
  schemaVersion: 1;
  currentUserId: DemoUserId;
  guestStatus: 'invited' | 'active' | 'revoked';
  comments: DemoComment[];
  approval: DemoApproval;
  activity: DemoActivity[];
}

interface DemoStore {
  read(): DemoState | null;
  write(state: DemoState): void;
  reset(): DemoState;
  available(): boolean;
}
```

- key 独立：`smart-edit:demo:collaboration:v1`；不读写真实 activity/version/draft。
- 初始状态由 `seedDemoState()` 生成；若 key 不存在、损坏或 schema 不匹配，返回 seed 并 `available=false` 提示。
- `reset()` 只覆盖 demo key；真实 draft/version/activity 不动。
- Demo activity 和真实 `activityStore` 分别持久化；UI 根据 `demoMode` 选择数据源。

替代方案：复用 `activityStore` 加 `sample` 标记。会和“真实 activity 不接受虚构参与者”的规则冲突，且关闭 demo 后要过滤；独立 store 更安全。

### D3 Topbar identity 与 shell 的 demo 分支

`TopBar` 增加 optional：

```ts
demoIdentity?: {
  name: string;
  initials: string;
  org: string;
  role: string;
} | null;
```

- `demoIdentity` 非空时，session chip 替换为 identity button：
  - 可见文字：`Chen Rui · Alpha Tech Ltd.`；
  - 一个 `Demo identity` tag；
  - 点击打开 Identity/People dialog（复用同一个 `people` module）。
- `demoIdentity` 为空时现有 `Local demo session` 文案不变。
- `EnvironmentStrip` 增加 `demoMode`、`onToggleDemo`、`onResetDemo`；demo banner 使用 `role="status"`。
- `AppShell.test` 现有“无身份”断言只在默认/demoIdentity 为空时成立；新增 demo identity 测试。

### D4 Identity / People 的 sample 数据与权限

`demoData.ts` 固定：

| id | name | org | role | demo capabilities |
|---|---|---|---|---|
| applicant | Chen Rui | Alpha Tech Ltd. | Applicant | start approval, comment |
| ops | Emma Wong | HSBC Trade Operations | Bank operations / first approver | approve/reject step 1, comment |
| compliance | Daniel Lee | HSBC Compliance | Compliance / second approver | approve/reject step 2, comment |
| lawyer | Lin Yan | Harbour Legal Partners | External counsel / guest | view + comment only |

- `DemoPeopleDialog` 显示 orgs、members、guest status；`Invite external counsel` / `Revoke guest` 只改 `guestStatus`，不创建真实邀请。
- 身份切换只改变 demo collaboration 的可用动作；不改变编辑器锁、审计或真实 API principal。
- 进行中的审批/评论操作使用当前 demo user id；如果当前用户不是 applicant，`Start approval` disabled；如果当前用户是 requester 或非当前 step 的 assignee，`Approve/Reject` disabled。
### D5 Approval 本地状态机

`DemoApproval`：

```ts
type ApprovalStatus = 'DRAFT' | 'IN_REVIEW' | 'APPROVED' | 'HANDED_OFF';

interface DemoApproval {
  status: ApprovalStatus;
  version: number;
  requesterId: DemoUserId;
  steps: Array<{
    role: 'ops' | 'compliance';
    assigneeId: DemoUserId;
    decision: 'approved' | 'rejected' | null;
    at: string | null;
  }>;
  receipt: string | null;
}
```

- `DRAFT`：applicant 可 `Start approval`；切到 `IN_REVIEW`，第一个未决 step active。
- `IN_REVIEW`：当前 step assignee 可 approve/reject；`approved` 推进到下一 step；`rejected` 回到 `DRAFT` 并清空后续 step decision。
- 两步均 approved → `APPROVED`；`Confirm sample handoff` → `HANDED_OFF`，receipt 固定写 `Simulated — no external system received the document.`
- 所有 decision/receipt 写入 demo store；没有网络请求。
- Demo 模式下 `Submit new version` 打开 Approval dialog（如果状态是 DRAFT，用户可先 Start approval）；诚实模式继续打开现有 `Submit new version` unavailable dialog。
- dialog 固定 `Simulated` 标签，避免误读真实审批。

### D6 Comments sample threads

`DemoComment`：

```ts
interface DemoComment {
  id: string;
  authorId: DemoUserId;
  text: string;
  quote: string | null;
  version: number;
  createdAt: string;
  resolved: boolean;
}
```

- seed 两条：Emma 对索赔条款的未解决评论、Lin Yan 的 guest 评论。
- `DemoCommentsDialog` 使用 `WorkspaceDialog`：
  - 新评论 textarea；若当前有 `selection`，展示 quote 并存入 comment。
  - 评论列表显示作者/角色/版本/时间/quote/状态；`Resolve` 按钮只改 demo store。
  - 作者固定为当前 demo identity；不允许伪造其他作者。
- 评论不写入任何真实服务。

### D7 Demo activity / Inbox

`DemoActivity`：

```ts
interface DemoActivity {
  id: string;
  actorId: DemoUserId;
  action: string;
  detail: string;
  at: string;
  read: boolean;
  notifiable: boolean;
}
```

- seed 4–6 条：version captured by applicant、audit completed、comment added by ops、approval requested。
- 新 demo 动作（identity switch 不记录；评论/审批/guest invite 可记录）append 到 demo activity。
- `Activity` dialog 在 demo mode 下使用 `DemoActivityPanel`（或 `ActivityPanel` 的 sample 变体），固定显示 `Sample data` 与 sample actor；不显示为真实 server audit。
- `Inbox` 在 demo mode 下用 demo activity 的 `notifiable` 派生；标记已读只写 demo store。
- 真实 `activityStore` 仍记录 import/save/audit 等真实操作；demo 模式下 topbar 计数显示 demo activity，真实日志保留但不混入。

### D8 Demo UI 组件

新增：

- `web/src/components/DemoIdentityDialog.tsx`（身份切换 + 角色说明）
- `web/src/components/DemoPeopleDialog.tsx`（组织/成员/guest）
- `web/src/components/DemoApprovalDialog.tsx`（状态机）
- `web/src/components/DemoCommentsDialog.tsx`
- `web/src/components/DemoActivityPanel.tsx` / `DemoNotificationPanel.tsx`
- 或复用 `ActivityPanel`/`NotificationPanel` 加 `sample` 变体；实现时优先复用外壳。

`App.tsx` 在 `moduleBody` 中按 `demoMode` 分支：

```ts
if (demoMode && module === 'people') return <DemoPeopleDialog ... />;
if (demoMode && module === 'approval') return <DemoApprovalDialog ... />;
if (demoMode && module === 'comments') return <DemoCommentsDialog ... />;
if (demoMode && module === 'activity') return <DemoActivityPanel ... />;
if (demoMode && module === 'inbox') return <DemoNotificationPanel ... />;
return <UnavailableModuleDialog ... />;
```

`Identity` 入口在 demo mode 下打开 `DemoIdentityDialog`；诚实模式仍是 `Authentication is not configured`。
### D9 Permissions and isolation

- Demo identity permissions 只影响 demo UI actions；真实编辑器/锁/审计/API 的 principal 不变，UI 文案明确这点。
- Demo store 与真实 store 使用不同 keys；关闭 demo mode 时不删除 demo state（保留以便再次打开），但 Activity/Inbox 不再读取它。
- `Reset demo data` 覆盖 demo key，不触碰真实 stores。
- Demo state 读取失败 → 使用 seed 并显示 session-only 提示；不阻塞主工作区。

### D10 Test strategy

- `demoMode.test.ts`：default false、persist on/off、storage failure fallback。
- `demoStore.test.ts`：seed、write/read、reset、schema mismatch、真实 activity key 不受影响。
- `DemoIdentityDialog`/`DemoPeopleDialog`：sample data、identity switch、guest invite/revoke、permissions。
- `DemoApprovalDialog`：DRAFT→IN_REVIEW→APPROVED→HANDED_OFF、reject、self-approval disabled、simulated receipt。
- `DemoCommentsDialog`：seed threads、add with/without quote、resolve、author = current identity。
- `DemoActivityPanel`/Inbox：seed events, count, mark read, separate from real activity。
- `App` integration：toggle on/off、default honest placeholders unchanged、demo modules render、Submit opens demo approval vs honest dialog。
- e2e：toggle demo、identity switch、People、Approval、Comments、Activity/Inbox；real mode placeholders；reset。
- Existing honest-mode tests must stay green without change.

## Risks / Trade-offs

- [Sample data mistaken for real identity/approval] → persistent banner、`Demo identity` tag、`Simulated` receipt、no network calls。
- [Real activity polluted by sample data] → separate demo store/key；Activity/Inbox choose source by mode。
- [Demo state persists but user expects reset on reload] → `Reset demo data` explicit；mode persists by design。
- [Permissions confusing] → label demo identity affects sample collaboration only；real editor/lock/audit principal unchanged。
- [Too many components for one batch] → keep first batch to four modules；use shared `WorkspaceDialog` and demo store, no backend。
- [Storage failure] → seed in memory and show session-only notice；never claim persistence。
- [Tests coupling to sample names] → test behavior via `DemoState`/ids, not exact copy beyond seeded examples。

## Migration Plan

1. Add demo mode/store + seed data；no existing key changes。
2. Wire toggle/banner into `EnvironmentStrip` and `AppShell` (default off)。
3. Add demo identity/People/Approval/Comments/Activity components and demo branches。
4. Wire Submit in demo mode to approval；keep honest dialog。
5. Add tests/e2e；default honest tests unchanged。
6. Rollback：remove demo components/store/toggle；real stores are untouched。

## Open Questions

无会改变规格或任务拆分的未决问题。真实身份/组织/邀请、后端审批/评论、HSBC/中文皮肤和完整访客表单留到后续 change。