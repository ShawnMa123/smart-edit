# Design

## Context

动机见 `proposal.md` — Why；行为契约见 `specs/approval-status-ui` 与 `specs/document-editor`。现状：

- `DocumentHead` 固定渲染 `<span className="tag tag--warn">Draft</span>`，与页脚 `Approval: Pending…` 冲突。
- `EnvironmentStrip` 仍写 “the assistant does not approve or submit”；`DocumentActions` 仍把 `Start approval` 列为 not implemented。
- `TopBar` 只渲染 Activity/People/Inbox/Developer；没有 Approval；Activity/Inbox badge 来自浏览器本地 `activity` 数组。
- 提交后 App 只设置 `lockNotice` 文本；`ApprovalPanel` 的 My submissions 是普通列表；页面不轮询。
- 所有提示共用 `notice--warn`；没有全局 Toast 或 live region。
- 现有 API 已提供 `/approvals`、`/documents/{id}`（含 `submission_status`/`submission`）、`/documents/{id}/submissions`、`/activity/unread-count`，本轮不需要后端改动。

## Goals / Non-Goals

**Goals:**

- 文档头、页脚、列表、顶部 badge 用同一份状态映射，提交后不再显示 Draft。
- 申请人提交后看到明确的等待审批 banner + stepper + 当前审批角色。
- Approval 的 My submissions 变成可读的状态卡片 + 时间线。
- 顶部有 Approval 入口与真实待办数；Activity 用服务端未读数。
- 即时结果用语义 Toast；持久状态保留内联 banner。
- 过期/矛盾文案在真实模式下消失。

**Non-Goals:**

- 不重做审批人左右分栏、不合并 Activity/Inbox、不做 SLA/意见模板/移动端重构。
- 不改后端表结构；不新增审批计数 API（前端用现有列表聚合）。
- 不引入外部 UI 库或图标库。

## Decisions

### D1 · 一个共享状态模型 + `StatusBadge`

新增 `web/src/domain/approvalStatus.ts`：

```ts
type Status = 'draft' | 'pending_first' | 'pending_second' | 'approved' | 'returned' | 'rejected';
interface StatusMeta {
  label: string;        // "Waiting for Bank Operations"
  shortLabel: string;   // "Pending first"
  tone: 'neutral'|'processing'|'success'|'warning'|'error';
  icon: string;         // ⏳ ✓ ↩ ✕ ●
  readOnly: boolean;
  nextActor: string|null;
  step: 0|1|2|3|4;
  description: string;
}
```

`StatusBadge` 只消费该映射；颜色只是辅助，文本 + 图标 + `aria-label` 是主体。备选“每个组件自己写 label”否决：已经出现 `Pending first approval / First approval / pending_first` 三套写法。

### D2 · `DocumentHead` 接收真实状态

`DocumentHead` 增加 `submission?: SubmissionSummary | null`（或 `submissionStatus`）。标题旁显示 `StatusBadge`；meta 行显示提交时间、revision、当前审批角色；退回时显示最新意见摘要。`Draft` 仅在 `submission_status === 'draft'` 时出现。

### D3 · `ApprovalStatusBanner` + Stepper

新增组件放在文档头与编辑器之间：

```text
[⏳ Waiting for Bank Operations]
① Submitted ✓ ─ ② Bank Operations ● ─ ③ Compliance ○ ─ ④ Approved ○
Submitted 14:02 · rev 3 · latest comment
Editing is locked until returned or approved.  [View approval]
```

数据来自 `draft.submission`（已有 `status/current_stage/created_at/revision/latest_comment`）。`returned` 时展示退回意见与 `Edit & resubmit` 提示；`approved` 时展示成功色与只读说明；`draft` 时不渲染 banner。

### D4 · My submissions 卡片 + 轮询

`ApprovalPanel` 的 `mine` 视图改为卡片列表：状态 badge、revision、提交时间、当前阶段、最新意见；点击卡片展示快照摘要 + 时间线（复用审批详情）。App/ApprovalPanel 在 `pending_*` 时每 10s 轮询 `GET /documents/{id}`；`approved/returned/rejected` 停止；`document.visibilityState !== 'visible'` 时暂停。

### D5 · 顶部真实计数

- `TOPBAR_ENTRIES` 增加 Approval（放在 Activity 旁）。
- `TopBar` 新增 `approvalCount` / `activityUnread` 两个可选 props；0 时隐藏 badge，>99 显示 `99+`。
- App 在 authenticated 模式：
  - `GET /approvals` 按当前角色聚合待办数；Approval badge 用它。
  - `GET /activity/unread-count` 获取服务端未读；Activity badge 用它。
  - fake/demo 模式保留原本地计数。
- 轮询与状态刷新共享一个 10s 定时器，避免每个 badge 单独请求。

### D6 · 轻量 Toast

新增 `ToastProvider` + `useToast()`（纯 React，无依赖）：

- 变体 `success | info | warning | error`；
- 右上角堆叠，最多 3 条；success 4s 自动关闭，error 手动关闭；
- `role="status"`（普通）/`role="alert"`（error），容器 `aria-live`；
- 支持 `actionLabel + onAction`（如 View approval）；
- 只用于即时反馈；只读、退回意见、冲突继续用内联 banner。

提交、审批决策、邀请复制改为 `toast.success(...)`；失败 `toast.error(...)`，保留表单/详情。

### D7 · 清理过期文案

- `EnvironmentStrip` 增加 `authenticated` prop：
  - 真实模式：`PG identity · server-backed drafts, approvals and activity`
  - demo：保留原 demo 文案
  - 删除 “does not approve or submit”。
- `DocumentActions` 从 `UNAVAILABLE_ACTIONS` 移除 `approve`；保留 export，并明确只有 export 不可用。
- `DocumentHead` 的 “history stored in this browser” 改为真实来源（server draft + approvals）。

### D8 · 兼容 fake / demo

## Risks / Trade-offs

- [轮询增加请求量] → 10s 间隔、页面隐藏暂停、终态停止、同一 tick 合并 document + approvals 请求。
- [顶部计数与页面状态短暂不一致] → 决策/提交成功后立即乐观更新并在下一次 tick 校准；失败回滚。
- [状态映射与后端枚举漂移] → 共享模块集中映射，未知状态显示 `Unknown` 并提供 `aria-label`，不静默当作 Draft。
- [Toast 抢焦点/干扰] → 非错误用 `aria-live=polite`，错误手动关闭；不自动聚焦 Toast。
- [fake 模式误显示真实状态] → 只有 `auth.status === 'authenticated'` 才渲染 banner/服务端 badge。
- [文案清理影响既有测试] → 先更新 `AppShell`/`DocumentActions`/`document-editor` 相关测试，再改文案；fake/demo 断言保持。
- [My submissions 卡片信息不足] → 本轮使用现有 `submission` 字段（revision/stage/comment）；提交人/审批人显示名留待后续。

## Migration Plan

1. 先合入状态模型、StatusBadge、文案清理与 DocumentHead 动态状态（P0）。
2. 再加 Toast、Pending Banner、My submissions 卡片、顶部计数与轮询（P1）。
3. 全部为前端改动，无数据库/API 迁移；回滚只需回退前端构建。
4. fake/demo 路径用现有测试保证不回退。

## Open Questions

- 轮询间隔固定 10s 是否合适？后续可做成配置或 SSE。
- 顶部 Approval badge 是否需要区分 first/second 两个数字？本轮先显示总数。
- 审批人/提交人显示名是否由后端补充？本轮先显示角色或 user id。
`fake` 或 `?demo=1` 不显示真实审批 banner、Approval 待办 badge、服务端计数；保留 DemoApproval / 本地 Activity；Toast 只用于本地操作，不伪造服务器提交成功。