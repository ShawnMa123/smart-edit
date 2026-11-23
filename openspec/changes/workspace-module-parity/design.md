# Design

## Context

见 `proposal.md` 的 Why。当前实现的关键约束：

- `web/src/App.tsx` 已经是三栏布局（`VersionPanel` / `RichEditor` / `AssistantPanel`），顶栏与文档头由 `AppShell.tsx` 提供；`.work-grid` 的直接子元素必须保持三个 pane，现有 `App.test.tsx` 依赖这一点。
- `workspace-shell` 已规定：没有认证时不得显示姓名、头像、组织作为当前身份，也不得提供“看起来能用”的成员管理入口。本设计不修改该规则；`People`、`Approval`、`Comments` 只做明确不可用占位。
- `interface-language` 已规定 chrome 英文；新增界面全部英文，不引入 HSBC/中文 mock 文案。
- 版本历史在 `web/src/versionStore.ts`，条目已有 `label`、`text`、`digest`、`createdAt`，比较可以直接在浏览器内完成。
- 现有活动信息只存在于后端 audit 表和前端 console/状态，没有面向操作者的 activity UI。
- 前端没有通用 dialog 组件；现有面板多为内联区域或原生 `window.confirm`。

## Goals / Non-Goals

**Goals:**

- 让主工作区在导航结构、入口位置、交互形态上接近参考原型，同时保持英文与 `smart-edit` 品牌。
- 提供真实可用的 Activity Log、Notifications、Version Compare 和 Implementation Map。
- 对没有后端能力的模块提供位置一致、措辞明确的占位，不伪造身份、组织、成员、审批人或评论。
- 保持现有三栏、编辑器投影、审计输入、版本历史不变。

**Non-Goals:**

- 不实现真实认证、组织/成员/邀请、审批工作流、评论服务、导出、语音或后端 API。
- 不复制 HSBC 品牌、中文 chrome、样例组织/当事人/审批人数据。
- 不把活动记录写成服务端审计；不新增数据库表。
- 不实现 mock 的字段确认、审批节点、访客权限或强制解锁模拟。

## Decisions

### D1 Shell 结构：topbar 保持外层，rail 与 workspace 进入 `.shell`

`App` 的渲染层级调整为：

```text
div.app
  TopBar(props: onOpenModule, activityCount, unreadCount, sessionLabel)
  EnvironmentStrip
  div.shell
    WorkspaceRail(active, onOpenModule)        // 桌面 58px；窄屏隐藏
    main.workspace
      DocumentHead
      ImportReport
      pane-tabs (narrow only)
      div.work-grid                            // 仍然是三个 pane
```

- `.shell { display:grid; grid-template-columns: 58px minmax(0,1fr); }`
- `.workspace { min-width:0; display:flex; flex-direction:column; }`
- 窄屏时 `.shell` 退化为单列，rail 隐藏，顶栏提供 `Menu` 入口。
- 不改变 `.work-grid` 的三列几何；现有 `App.test.tsx` 的 `.work-grid > *` 断言继续成立。

替代方案：把 rail 放进 `.work-grid` 作为第四列。会破坏三 pane 断言，也混淆“导航”与“内容 pane”，拒绝。

### D2 导航模型：`WorkspaceModule` + 现有 `PaneId`

新增：

```ts
type WorkspaceModule =
  | 'activity'
  | 'inbox'
  | 'people'
  | 'identity'
  | 'developer'
  | 'approval'
  | 'comments';
```

- `Document` → `setPane('editor')`
- `Versions` → 桌面 `setPane('versions')`；窄屏切换 pane
- `Activity` / `Inbox` / `People` / `Identity` / `Developer` / `Approval` / `Comments` → 打开对应 dialog
- rail 的 `active` 只表达当前内容 pane 或当前打开的模块；用 `aria-current` / `aria-pressed` + 文字/图标，不依赖颜色。
- `TopBar` 的 `People`、`Inbox`、`Activity`、`Developer` 与 rail 复用同一 `onOpenModule`，避免两套逻辑。

不引入路由库。当前应用是单文档工作区，dialog 状态即可表达；引入 router 会扩大打包与测试面。

### D3 通用 `WorkspaceDialog`，不使用原生 `<dialog>`

新增 `web/src/components/WorkspaceDialog.tsx`：

- props: `title`, `children`, `onClose`, `footer?`, `wide?`
- 渲染 backdrop + `role="dialog"` + `aria-modal="true"` + `aria-labelledby`
- 打开时聚焦标题或第一个可聚焦元素；`Escape` 关闭；点击 backdrop 关闭；关闭后焦点回到触发按钮（由调用方保存 `document.activeElement`，或由 App 在 open 时记录）。
- 使用条件渲染而不是原生 `showModal()`：jsdom 对 `<dialog>` 支持不一致，现有测试环境以 Testing Library 为主。
- 所有 dialog 文案英文；不可用占位和实现状态表都用同一外壳。

替代方案：原生 `<dialog>` 提供免费 focus trap，但 jsdom mock 复杂；不选。

### D4 Activity store：独立模块、可注入 storage、按文档隔离

新增 `web/src/workspace/activityStore.ts`：

```ts
type ActivityKind =
  | 'import' | 'save' | 'capture' | 'restore' | 'audit'
  | 'knowledge' | 'template' | 'export-attempt' | 'conflict';

interface ActivityEntry {
  id: string;
  kind: ActivityKind;
  action: string;       // 英文短句，例如 "Version captured"
  detail: string;       // 不含问题/正文，只描述结果
  at: string;           // ISO
  read: boolean;
  notifiable: boolean;
}

interface ActivityStore {
  list(documentId: string): ActivityEntry[];
  record(documentId: string, input: Omit<ActivityEntry, 'id' | 'at' | 'read'>): ActivityEntry;
  markAllRead(documentId: string): void;
  clear(documentId: string): void;
  available(): boolean;
}
```

- `localStorage` key: `smart-edit:activity:<documentId>`，与版本历史一样按文档隔离。
- `MAX_ACTIVITY = 100`；新条目在前；超出淘汰最旧。
- storage 读/写异常时退回内存数组，并暴露 `available=false`；UI 显示 `Activity is session-only because browser storage is unavailable.`
- `record` 只接收 action/detail，不接受 user/org；默认来源由 UI 文案表达为 `browser`。
- `id` 使用 `a-${Date.now()}-${sequence}`；同毫秒重复也稳定。
- 不记录 question、文档正文、citation 内容、API key、用户标识。

替代方案：React Context 全局 store。需要新增 provider、测试包装、跨组件订阅；当前只有 App 和少数回调需要，显式 props 更简单。

### D5 Activity 记录点与事件语义

| 触发点 | kind | detail 示例 | notifiable |
|---|---|---|---|
| 导入解析成功 | `import` | `Parsed 2 file(s)` | 是 |
| 导入失败 | `import` | `Import failed: <code>` | 是 |
| 草稿保存成功（用户编辑后） | `save` | `Draft revision 7 saved` | 否 |
| 保存冲突 | `conflict` | `Save conflict; recovery draft kept` | 是 |
| Capture version | `capture` | `Version 3 captured` | 是 |
| Restore version | `restore` | `Version 2 loaded as draft` | 否 |
| 审计开始 | `audit` | `Audit started` | 否 |
| 审计成功 | `audit` | `Audit completed: 0 findings` | 是 |
| 审计失败 | `audit` | `Audit failed: <code>` | 是 |
| 知识问答完成 | `knowledge` | `Knowledge answer: answered` | 是 |
| Template apply | `template` | `Template applied` | 是 |
| Export 不可用尝试 | `export-attempt` | `Export unavailable` | 否 |
| 清理 activity | — | 不记录新事件 | — |
| 标记通知已读 | — | 不记录事件 | — |

- `handleImport` 成功/失败、`handleCapture`、`handleRestore`、`handleRunAudit`、`handleApplyTemplate` 由 App 记录。
- `applySaveResult` 只在 `userEditedRef.current` 为真时记录，避免首载恢复也产生“保存”事件。
- `KnowledgePanel` 新增可选 `onActivity?: (kind, action, detail) => void`；在回答完成/失败时调用。App 通过 `AssistantPanel` 透传；不把 store 直接耦合进面板。
- `DocumentActions` 新增可选 `onUnavailableAction?: (action) => void`；App 记录 `export-attempt`。
- 事件顺序：先完成业务状态更新，再 `record`；记录失败不影响业务。

### D6 Notifications 是活动的一个派生视图

- `unreadCount = activity.filter(e => e.notifiable && !e.read).length`
- `Inbox` 打开时调用 `markAllRead(documentId)` 并刷新 App 状态；不发送网络请求。
- Inbox 列表只显示 `notifiable` 条目；每项显示 action、detail、time、`Unread` 标签（若未读）。
- 空状态：`No notifications yet`，说明通知来自真实本地操作。
- 不创建“任务分配”“审批催办”等没有数据源的条目。

替代方案：独立 notifications store。会和 activity 重复；派生视图足够。

### D7 Version Compare：VersionPanel 本地选择 + 独立 dialog + 段落 diff

- `VersionPanel` 增加多选状态（`selectedForCompare: string[]`，最多 2）。
  - 每条版本前加 checkbox；选中超过 2 时禁用未选中的 checkbox，并显示 `Select two versions to compare.`
  - `Compare versions` 按钮在两个选中时启用；否则 disabled 并给出原因。
  - 现有 `Compare versions — not implemented` 文案移除；现有测试相应更新。
- `onCompare(ids: [string, string])` 由 App 打开 `VersionCompareDialog`。
- `VersionCompareDialog` 使用 `versionStore.get` 读取两条版本；标题包含 label、时间、短 digest。
- diff 算法：
  - 将每版 `text` 按 `/\n{2,}/` 切块（与 `projectDocument` 的块分隔一致）。
  - 对块序列做 LCS；输出 `same` / `removed` / `added` 行。
  - 相邻 `removed` + `added` 合并为 `changed` 行，左右并排显示 before/after。
  - 不推断语义，不生成 AI 摘要；只展示文本。
- 无差异：显示 `No textual differences in the captured text.`
- 只有一条或没有版本：Compare 不可用；空状态说明先 capture。
- 比较不调用 `versionStore.capture`、不写 draft、不发网络请求。

替代方案：引入 diff 库。为保持依赖最小，手写 LCS（块数量最多 20×段落数，规模很小）。
### D8 Developer / Implementation Map：静态表，不发请求

新增 `web/src/components/ImplementationMap.tsx`，内容为静态数组：

| Module | Status | Limitation |
|---|---|---|
| Document | Available | Real editor, paper view and autosave |
| Versions | Available | Browser-local capture/restore; compare is local |
| Activity | Available | Browser-local, not server audit |
| Notifications | Available | Derived from local activity |
| Knowledge / Audit / Automation | Available/Partial | See tab status |
| People / Identity | Unavailable | No authentication or organisation service |
| Approval | Unavailable | No approval workflow backend |
| Comments | Unavailable | No comment service |
| Export | Unavailable | No export adapter |
| Voice | Unavailable | Not in this build |

- 状态用文字 `Available` / `Partial` / `Unavailable`，颜色只作辅助。
- 不列 API endpoint、不写“已实现”除非真实存在。

### D9 不可用占位：位置一致、措辞明确、零副作用

- `People`：标题 `Organisation & members — not available in this build`；说明需要认证/组织/成员/邀请服务；不显示任何成员行。
- `Identity`：标题 `Authentication is not configured`；说明当前只有 `Local demo session`；不显示样例姓名/邮箱/角色。
- `Approval`：标题 `Approval workflow — not available in this build`；说明需要固定快照审批、独立审批人和 Workflow Command；不显示审批人/节点/回执。
- `Comments`：标题 `Comments — not available in this build`；说明没有评论服务；不显示样例评论。
- 占位 dialog 只含 Close；不发送网络请求、不写 activity（用户主动触发 export attempt 等真实尝试除外）。

### D10 英文-only 与诚实约束

- 新增所有 chrome 文案英文；不引入 CJK（`interface-language` e2e 会扫描）。
- 不出现 `HSBC`、`Alpha Tech`、`DG-2026-00417`、`跨组织共享`、`见索即付保函` 等 mock 样例。
- 活动记录无 actor 姓名；通知无 sender/assignee。
- `AppShell` 现有“无身份”测试保持通过；新增测试断言 People/Identity 占位不含成员行、邮箱或组织名。

### D11 样式与响应式

- 复用现有 tokens（`--canvas`、`--border`、`--radius`、`--accent`、status tokens）。
- 新增：
  - `.shell` / `.workspace` / `.rail` / `.rail button` / `.rail .active`
  - `.topbar-actions` 扩展（保留 `.topbar-actions` 类名）
  - `.activity-list` / `.activity-entry` / `.notification-list` / `.badge`
  - `.dialog-backdrop` / `.dialog` / `.dialog-head` / `.dialog-body` / `.dialog-foot`
  - `.diff-grid` / `.diff-row` / `.diff-row--same|added|removed|changed`
- rail 宽 58px；窄屏隐藏 rail，`.pane-tabs` 增加 `More` 入口打开模块列表。
- 所有状态同时有文字；focus-visible 保留现有全局规则。

### D12 测试策略

- `activityStore.test.ts`：record/list/cap/order、clear、markAllRead、storage unavailable fallback、按 documentId 隔离。
- `WorkspaceDialog.test.tsx`：role/aria、Escape、backdrop、focus return（可测）。
- `WorkspaceRail.test.tsx` / `TopBar` 扩展：entries、active 文字/aria、counts、窄屏 menu。
- `ActivityPanel.test.tsx`：list/empty/clear confirm、notifications/unread、英文与无 actor。
- `VersionPanel.test.tsx` 更新：checkbox、max two、Compare enabled/disabled、onCompare。
- `VersionCompareDialog.test.tsx`：same/added/removed/changed、no differences、no mutation。
- `ImplementationMap.test.tsx`：状态与限制文案、无 endpoint。
- `App.test.tsx`/e2e：rail 打开 dialog、People/Identity 占位无样例、Activity 记录一次真实操作、Compare 两个版本、English-only、narrow 入口。
- 现有 `App.test.tsx` 对 `.work-grid > *` 的断言必须保持；`VersionPanel` 旧 `not implemented` 断言删除并替换。

## Risks / Trade-offs

- [Scope creep: 把 comments/approval 做成半功能] → 本 change 只做明确占位；任何写入能力留到后续 change。
- [Activity 噪音] → 只记录用户可见操作；save 成功仅在用户编辑后记录；上限 100；clear 不记录自身。
- [本地活动被误认为服务端审计] → dialog 固定文案 `Browser-local activity — not a server audit trail`；没有后端写入。
- [与未归档的 `workspace-visual-parity` 冲突] → 复用其 tokens/类名；不修改它的规范；新 change 只新增 rail/模块，保留其三栏和 no-identity 规则。
- [窄屏入口过多] → rail 隐藏，TopBar `Menu` + pane tabs；e2e 检查无横向滚动。
- [Compare 算法在大文档上卡顿] → 只比较用户显式选中的两个版本，按块 LCS；版本最多 20 条，块数有限。
- [Dialog 焦点管理不完整] → 可访问性测试覆盖 Escape/焦点返回；复杂 focus trap 留待后续如果需要。

## Migration Plan

1. 新增 activity store 和组件；旧 localStorage 键不受影响。
2. `App.tsx` 接入 shell/rail/dialog 与 activity 记录；现有版本/编辑器/审计行为不变。
3. `VersionPanel` 替换 compare 占位为本地比较；旧版本条目结构不变。
4. 新增 e2e 断言，更新旧测试；全部通过后合并。
5. 回滚：删除新组件/store 并还原 `App.tsx`/`VersionPanel`；没有数据库或 API 迁移。

## Open Questions

无会改变规格或任务拆分的未决问题。评论、组织成员、审批和导出作为后续独立 change。