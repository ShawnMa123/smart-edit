# Design

## Context

见 `proposal.md` 的 Why。当前实现的关键约束：

- `RichEditor` 已经有 `TOOLS`（Paragraph/H1/H2/H3/B/I/U/lists/undo/redo）和 `TABLE_TOOLS` 全部平铺在 toolbar，footer 只有字符数与 paper 说明。
- `App.tsx` 启动时自动 `acquireLock`，`lockRef`/`lockHeld` 是唯一锁来源；`releaseLock` 客户端函数已存在，但没有 UI。
- 共享版本提交没有后端接口；`versionStore.capture` 只是浏览器本地捕获。
- `DocumentActions` 把 `Formatting`、`Export`、`Start approval` 都放进 `UNAVAILABLE_ACTIONS`，其中 Formatting 已过时（toolbar 实际支持格式）。
- `workspace-shell` 要求状态带持续显示 save/snapshot/lock；`rich-text-editing` 要求所有格式能力仍可用；本设计不改变这些事实，只改变控制形态。

## Goals / Non-Goals

**Goals:**

- 让编辑区底部出现与参考原型一致的动作层，同时保持每个动作真实或有明确不可用说明。
- 降低 toolbar 的视觉密度，但保留所有格式能力、active 状态和键盘快捷键。
- 文档头提供 Comments 入口，移除过时的 Formatting 不可用项。
- 状态带保持原有四项事实，压缩为更接近 mock 的 lock-line。

**Non-Goals:**

- 不实现服务端共享版本提交、审批工作流、评论服务、导出或真实组织/身份。
- 不复制 HSBC 品牌、中文 chrome 或样例数据。
- 不改变富文档投影、审计输入、版本历史或锁的 API 契约。

## Decisions

### D1 Footer 动作由 `RichEditor` 暴露，App 负责真实锁/提交逻辑

`RichEditorProps` 增加：

```ts
onReleaseLock?: () => void | Promise<void>;
onStartEditing?: () => void | Promise<void>;
onSubmitVersion?: () => void;
```

- footer 渲染：

```text
[Release lock] [Start editing]                      [Submit new version]
```

- `lockHeld=true`：Release enabled，Start editing disabled。
- `lockHeld=false`：Release disabled，Start editing enabled。
- `Submit new version` 始终 enabled；点击只打开 App 的提交说明 dialog。
- 动作按钮用真实 handler，不在 `RichEditor` 内部调用 API；这样组件仍可在测试中单独验证 enabled/disabled/callback。

替代方案：把三个按钮做成纯静态样式。会看起来像可用但实际没有行为，拒绝。

### D2 Release / Start editing 复用现有锁 API

`App.tsx` 增加：

```ts
const handleReleaseLock = async () => {
  const lock = lockRef.current;
  if (!lock) return;
  // 未保存内容仍留在编辑器；release 只释放锁，不丢弃本地内容。
  await releaseLock(facts.documentId, lock.lock_id);
  lockRef.current = null;
  setLockHeld(false);
  setSaveState('local');
};

const handleStartEditing = async () => {
  const current = draftRef.current;
  if (!current || lockRef.current) return;
  const next = await acquireLock(current.document_id, current.draft_id);
  lockRef.current = next;
  setLockHeld(true);
  setSaveState('saving');
  scheduleSave(richDocRef.current);
};
```

- `releaseLock` 失败时保留锁状态并显示错误，不假装已释放。
- `Start editing` 成功后才把 `lockHeld` 设为 true；先 acquire 再 scheduleSave，避免无锁保存。
- 如果 release 时有未保存内容，UI 文案说明“content remains in this browser; release only drops the lock”，不自动丢弃。
- 现有自动 acquire 行为保留；`Start editing` 主要用于 release 后重新获取。
- 锁状态仍由 `editor-status` 的 `lock: ...` 文案表达，不新增第二套状态。

替代方案：用 mock 的 keep-discard release 对话框。会增加一个未要求的确认流程和本地草稿分支；本 change 先保持“release 不丢内容”。

### D3 Submit new version：位置保留，行为诚实降级

App 增加 `submitOpen` state，并复用 `WorkspaceDialog`：

```text
Title: Submit new version
Body:  Shared version submission is not available in this build.
       The document is not sent to a server and no approval is started.
       You can still capture a browser-local version for comparison.
Footer: [Close] [Capture browser-local version]
```

- `Capture browser-local version` 调用现有 `handleCapture()`，成功后关闭 dialog；版本列表/current marker 照常更新。
- dialog 不显示成功回执，不说 submitted/sent/approved。
- `Submit new version` 保留主按钮视觉（接近 mock），但点击不提交。

### D4 Document header：Comments 入口 + 移除 Formatting 不可用项

`DocumentActions` 调整：

```ts
UNAVAILABLE_ACTIONS = [
  { id: 'export', ... },
  { id: 'approve', ... },
];
```

新增 optional `onComments?: () => void`，在 Import 之后渲染真实可点击的 `Comments` 按钮。

- `Comments` 调用 `openModule('comments')`，复用 `UnavailableModuleDialog` 的 Comments 文案。
- `Export` / `Start approval` 仍显示 `Not available`，点击只显示原因。
- 不再显示 `Formatting · Not available`；格式化由 toolbar 提供。
- 动作顺序：Import file → Comments → Export → Start approval（mock 的顺序，去掉 Formatting）。
- `Import file` 继续是唯一 primary 动作；Approval 不可用，不能成为 primary。

### D5 Toolbar：block-format select + 分组 table 菜单

`RichEditor` 的 toolbar 结构调整：

```text
[Paragraph v] | B I U | • 1. | Table v | ↶ ↷ | Find | Var
```

- `BLOCK_FORMATS`：Paragraph / Heading 1 / Heading 2 / Heading 3。
  - `<select aria-label="Paragraph style">`；`value` 由 `editor.isActive('heading', {level})` 推导，否则 `paragraph`。
  - `onChange` 执行 `setParagraph()` 或 `toggleHeading({level})`。
  - 保留标题投影规则 `#`/`##`/`###`。
- `INLINE_TOOLS`：Bold、Italic、Underline、Bullet list、Ordered list、Undo、Redo。
- `Table` 分组：`<details className="toolbar-menu">`，summary `Table`；内部保留 Insert table、+R/−R、+C/−C。
  - 键盘可打开 details 并激活内部按钮。
  - 现有 `insertTable` 行为不变。
- Find 与 Mark as variable 保留在 toolbar 右侧。
- 所有 toolbar active 状态继续只读 `editor.isActive()`，不使用本地 pressed state。
- 现有 `TOOLS`/`TABLE_TOOLS` 可以拆分/重命名；保留导出类型供测试使用，但不再平铺渲染。

替代方案：保留 H1/H2/H3 按钮，只做 CSS 换行。视觉密度仍不足，且与 mock 的 block-format select 差太远；不选。

### D6 状态带压缩为 lock-line，事实不变

`editor-status` 保留 `data-testid`、`save-state` 和四项信息：

```text
snapshot v3 | draft rev 7 | lock: this session | Saved to server
```

- 外层改为一行 flex-wrap，使用 `.status-chip` 小标签；不改变文案分支。
- `editor-footer` 左侧保留 `{n} characters in the audit text` 与 `Paper view...`，右侧放动作条。
- 不把字符数移进状态带；现有测试断言保持。

### D7 样式

- 文档头 `h1` 从 17px 调到 19px；header padding 向 mock 的 17/23/14 靠拢。
- `.editor-footer` 使用 `display:flex; justify-content:space-between; flex-wrap:wrap; gap`。
- `.editor-footer-actions` 右对齐；移动端换行。
- `.toolbar select` 与现有按钮同高；`.toolbar-menu` 使用绝对定位菜单，避免把表格操作挤在一行。
- `.status-chip` 使用现有 `--canvas`/`--border`/muted token。
- 不改变 `--accent`，继续 smart-edit navy；不引入 HSBC red/中文。

### D8 测试

- `RichEditor.test.tsx`：
  - block-format select 存在，选项 Paragraph/H1/H2/H3；选择后投影/active 正确。
  - `Table` 菜单打开后 Insert table/+R/−R/+C/−C 可操作；原 `Insert table` 测试改为先打开菜单。
  - footer 三个按钮的 enabled/disabled 与回调；Release/Start editing 在 lockHeld 两种状态下互换。
  - `editor-status`/`save-state`/字符数断言保持。
- `DocumentActions.test.tsx`：
  - Comments 按钮出现在 Import 后；点击调用 `onComments`。
  - `UNAVAILABLE_ACTIONS` 不再含 Formatting；Export/Start approval 仍标记不可用。
- `App.test.tsx` 或新 `App.submit.test.tsx`：
  - Submit new version 打开 dialog；dialog 文案明确不可用；不显示 submitted/sent。
  - Capture 动作调用 capture，dialog 关闭，版本列表更新。
  - 锁 release/start 的 API 调用可用 mock 客户端验证（或 App 层集成测试）。
- e2e：
  - footer 三个按钮可见；Submit dialog/capture 路径。
  - toolbar block-format select 与 Table 菜单仍能格式化；English-only/overflow 保持。

## Risks / Trade-offs

- [Release lock 时未保存内容丢失] → release 不删除编辑器内容，只释放锁；状态改为 local，文案说明内容仍在浏览器。
- [Start editing 后保存失败] → 保留锁状态，显示 save error；不把失败写成 saved。
- [Submit 对话框被误读为真实提交] → 固定文案 `not available in this build`；不显示回执；动作名 `Capture browser-local version` 明确本地。
- [Toolbar 分组降低可发现性] → block-format select 带 aria-label，Table summary 可键盘打开；e2e 覆盖。
- [移除 Formatting 按钮影响旧测试] → 更新 DocumentActions 测试；编辑器格式化能力仍在 toolbar，满足 `document-editor` 原要求。
- [状态带压缩导致信息不可读] → 保留四个文字 chip 和 `save-state` testid；窄屏换行而不是隐藏。

## Migration Plan

1. 先改 `DocumentActions`（去掉 Formatting、加 Comments）并更新测试。
2. 改 `RichEditor` toolbar/footer/status 并更新组件测试。
3. 改 `App.tsx` 接锁动作与 Submit dialog；更新 App 测试。
4. 调整 `styles.css` 并做 1440/1024/窄屏视觉检查。
5. 回滚：还原上述组件与样式；无数据库/API 迁移。

## Open Questions

无会改变规格或任务拆分的未决问题。共享提交、审批和评论服务仍是后续独立 change。
替代方案：直接把 footer 主按钮改名为 `Capture version`。更简单，但和 mock 的主按钮位置/语义差距更大；用户已选择保留 Submit 位置。