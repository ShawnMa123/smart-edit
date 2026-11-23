# Tasks

## 1. Activity store foundation

- [x] 1.1 新增 `web/src/workspace/activityStore.ts`：定义 `ActivityKind`、`ActivityEntry`、`ActivityStore`，实现按 `documentId` 隔离的 `localStorage` key、最多 100 条、新条目在前、`record/list/markAllRead/clear`，并在 storage 不可用时退回内存并暴露 `available=false`；验证：`npm --prefix web run test -- src/workspace/activityStore.test.ts` 通过。
- [x] 1.2 新增 `web/src/workspace/activityStore.test.ts`：覆盖顺序、上限淘汰、clear、markAllRead、storage 抛错回退、两个 documentId 互不影响；验证：同一 vitest 文件全部通过。
- [x] 1.3 在 `web/README.md` 记录 activity 的 store key、browser-local 边界和“不是 server audit”；验证：README 中可 grep 到 `smart-edit:activity:` 与 `not a server audit`。

## 2. Dialog, rail and top-bar primitives

- [x] 2.1 新增 `web/src/components/WorkspaceDialog.tsx`：`role="dialog"`、`aria-modal`、`aria-labelledby`、Escape/backdrop 关闭、关闭后焦点回到触发元素；验证：新增 `WorkspaceDialog.test.tsx` 覆盖 role/aria、Escape、backdrop 与 focus return。
- [x] 2.2 新增 `web/src/components/WorkspaceRail.tsx`：Document/Versions/Approval/Comments/People/Developer 入口、active 的 `aria-current` 与文字/视觉标记、键盘可达；验证：新增 `WorkspaceRail.test.tsx` 覆盖入口、active、键盘与 accessible name。
- [x] 2.3 扩展 `web/src/components/AppShell.tsx` 的 `TopBar`：接收 `onOpenModule`、`activityCount`、`unreadCount`、`sessionLabel`，渲染 Activity/People/Inbox/Developer 与中性 session；保持不出现姓名/头像/组织；验证：更新 `AppShell.test.tsx`，新增 counts 与 action 断言，原 no-identity 断言仍通过。
- [x] 2.4 在 `web/src/styles.css` 增加 `.shell`、`.workspace`、`.rail`、`.topbar-actions`、`.badge`、`.dialog-*` 的基础样式，复用现有 tokens；验证：`npm --prefix web run build` 成功且新增类名可 grep。

## 3. App shell integration and explicit placeholders

- [x] 3.1 调整 `web/src/App.tsx` 为 `TopBar → EnvironmentStrip → .shell(.rail + .workspace(DocumentHead/ImportReport/pane-tabs/.work-grid))`，保持 `.work-grid` 直接子元素仍是三个 pane；验证：`App.test.tsx` 的 pane 断言、`App.draft.test.tsx`、`App.rich.test.tsx` 全部通过。
- [x] 3.2 在 `App.tsx` 增加 `WorkspaceModule` 状态与 `openModule/closeModule`，把 rail/topbar 的 Activity/Inbox/People/Identity/Approval/Comments/Developer 接到同一个 handler；验证：新增 `App` 级测试点击每个入口，断言对应 dialog 标题。
- [x] 3.3 新增 `web/src/components/UnavailableModuleDialog.tsx`（或等价组件）：People、Identity、Approval、Comments 四类明确占位，说明缺失后端能力，不含样例成员/组织/审批人/评论，且不写数据/不发请求；验证：新增测试断言 `not available in this build`、缺失能力说明，以及不出现邮箱、组织名、成员行。
- [x] 3.4 在窄屏（`useNarrowViewport`）隐藏 rail，并在 `.pane-tabs` 增加 `More` 入口/模块菜单，保证同一组入口可达且无横向滚动；验证：新增/更新窄屏 e2e 断言入口可达与 `scrollWidth <= clientWidth`。
- [x] 3.5 新增 `web/src/components/ImplementationMap.tsx` 静态只读表，列出 Module/Status/Limitation，不写 API endpoint；在 Developer dialog 中渲染；验证：新增 `ImplementationMap.test.tsx` 覆盖 Available/Partial/Unavailable 文案与无 endpoint。

## 4. Activity and notifications UI

- [x] 4.1 新增 `web/src/components/ActivityPanel.tsx`：Activity dialog 展示 newest-first、action/detail/time、空状态、`Browser-local activity — not a server audit trail`、storage 不可用的 session-only 提示；Clear 需二次确认；验证：新增 `ActivityPanel.test.tsx` 覆盖 list/empty/clear confirm/storage notice。
- [x] 4.2 新增 `web/src/components/NotificationPanel.tsx`：Inbox 只显示 `notifiable` 本地活动，未读标记、Mark all read、空状态；验证：新增 `NotificationPanel.test.tsx` 覆盖过滤、未读、mark read 与无 sender/assignee。
- [x] 4.3 在 `App.tsx` 接入 activity 记录：import 成功/失败、用户编辑后的 save 成功、conflict、capture、restore、audit start/success/failure、template apply；按 design D5 的 kind/detail/notifiable 表实现；验证：新增 App 集成测试逐项触发并断言 activity 条目，且首载不产生 save 事件。
- [x] 4.4 给 `KnowledgePanel` 增加可选 `onActivity`，由 `AssistantPanel` 透传；在回答完成/失败时记录 `knowledge` 事件；给 `DocumentActions` 增加 `onUnavailableAction`，在 Export 不可用尝试时记录 `export-attempt`；验证：更新 `KnowledgePanel.test.tsx`、`DocumentActions.test.tsx`，新增回调断言。
- [x] 4.5 在 `web/README.md` 增加 activity event 表和“只记录真实本地事件、不含问题/正文/身份”的说明；验证：README 可 grep 到 `Activity`, `browser-local`, `notifiable`。

## 5. Version comparison

- [x] 5.1 新增 `web/src/workspace/versionDiff.ts`：按 `/\n{2,}/` 切块，LCS 输出 same/removed/added，并把相邻 removed+added 合并为 changed；验证：新增 `versionDiff.test.ts` 覆盖相同、纯新增、纯删除、替换、空文本。
- [x] 5.2 新增 `web/src/components/VersionCompareDialog.tsx`：显示两个版本的 label/time/short digest，并排渲染 diff rows，无差异时显示 `No textual differences in the captured text.`；不生成 AI 摘要；验证：新增 `VersionCompareDialog.test.tsx`。
- [x] 5.3 修改 `web/src/components/VersionPanel.tsx`：每版本 checkbox、最多选 2、未选满时 Compare disabled 并说明原因、选中两项时调用 `onCompare([id1,id2])`；移除 `Compare versions — not implemented`；验证：更新 `VersionPanel.test.tsx`，覆盖 max two、disabled/enabled、callback。
- [x] 5.4 在 `App.tsx` 接入 `onCompare` 打开 `VersionCompareDialog`；比较不改 versionStore、不改当前 draft、不发网络请求；验证：新增 App 集成测试断言比较前后版本数量/`currentVersionId`/draft 不变。
- [x] 5.5 在 `web/README.md` 记录 compare 的 browser-local、只读、无 AI 摘要边界；验证：README 可 grep 到 `Version compare` 与 `read-only`。

## 6. Integration verification and visual parity

- [x] 6.1 新增/更新 Playwright e2e：rail 入口打开对应 dialog、People/Identity 占位无样例身份、Activity 记录一次真实操作、Inbox 未读计数、两个版本 compare、English-only chrome、窄屏入口无横向滚动；验证：`npm --prefix web run e2e -- --project=desktop` 与 narrow project 通过。
- [x] 6.2 更新 `web/README.md` 的 shell/module 章节，说明 rail、topbar actions、activity、notifications、compare、implementation map 以及 People/Approval/Comments 的不可用边界；验证：文档中的命令与实际 `npm --prefix web` scripts 一致，且可 grep。
- [x] 6.3 运行 `npm --prefix web run typecheck && npm --prefix web run test && npm --prefix web run build`，修复所有回归；验证：三条命令退出码为 0。
- [x] 6.4 在 1440×900 与 1024×800 对照 `tradeAI_requirementDesign_v2/HSBC_Nexus_Document_Editor_Mock_Demo.html` 做视觉检查：rail 宽度/位置、topbar action 顺序、dialog 形态、无 HSBC/中文/样例组织、无横向滚动；验证：截图对照并记录结果，未通过项不得勾选。

## Workflow follow-up

- Archive this change after the project's review requirements are satisfied.
- Confirm `workspace-navigation` and `workspace-activity` purposes are carried into the main specs, and the `document-editor` version-compare requirement is present.
- 后续 change 再处理真实组织/成员/身份、评论、审批、导出和语音；本 change 不实现这些后端能力。