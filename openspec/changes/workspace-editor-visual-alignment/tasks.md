# Tasks

## 1. Document header actions

- [x] 1.1 修改 `web/src/components/DocumentActions.tsx`：从 `UNAVAILABLE_ACTIONS` 移除 `format`，新增可选 `onComments`，在 Import 后渲染真实 Comments 按钮；动作顺序为 Import file → Comments → Export → Start approval；验证：`DocumentActions.test.tsx` 覆盖 Comments 回调、Formatting 不再出现、Export/Approval 仍标 Not available。
- [x] 1.2 在 `App.tsx` 把 `onComments` 接到 `openModule('comments')`，复用现有 Comments 占位；验证：App 测试点击头部 Comments 打开 `Comments — not available in this build`，且不出现样例评论。
- [x] 1.3 更新 `web/README.md` 的 document header 说明（Comments 占位、Formatting 由 toolbar 提供）；验证：README 可 grep 到 `Comments` 与 `toolbar`。

## 2. Toolbar density

- [x] 2.1 修改 `RichEditor.tsx`：新增 block-format `<select aria-label="Paragraph style">`（Paragraph/Heading 1/2/3），移除平铺的 Paragraph/H1/H2/H3 按钮；保留 `#`/`##`/`###` 投影规则；验证：`RichEditor.test.tsx` 覆盖 select 选项、选择后的 active/投影，原日期分块测试不变。
- [x] 2.2 把 Insert table/+R/−R/+C/−C 收进可键盘打开的 `Table` details 菜单，保留 `Insert table` 行为；验证：测试先打开 Table summary，再点击 Insert table/+R 等，表格结构仍正确。
- [x] 2.3 在 `styles.css` 增加 block-format select 与 `.toolbar-menu` 样式，保持 toolbar 单行/可换行且不横向溢出；验证：`npm --prefix web run build` 通过，1440/1024 截图无 overflow。

## 3. Footer actions and status band

- [x] 3.1 扩展 `RichEditorProps`：`onReleaseLock`、`onStartEditing`、`onSubmitVersion`；footer 渲染 `Release lock` / `Start editing` / `Submit new version`，按 `lockHeld` 切换前两个按钮的 disabled；验证：`RichEditor.test.tsx` 覆盖两种锁状态与回调。
- [x] 3.2 压缩 `editor-status` 为一行 flex-wrap 的 `.status-chip` 结构，保留 snapshot/draft/lock/save 四类文案、`data-testid="editor-status"` 和 `save-state`；footer 左侧保留字符数/paper 文案；验证：现有 `RichEditor.test.tsx` 的 save-state/字符数断言更新后通过。
- [x] 3.3 在 `styles.css` 增加 `.editor-footer-actions`、`.status-chip` 与 footer 布局；验证：1440/1024/412 视口无横向滚动，footer 动作可见。

## 4. Real lock actions

- [x] 4.1 在 `App.tsx` 引入 `releaseLock`，实现 `handleReleaseLock`：释放真实锁、清空 `lockRef`、`lockHeld=false`、`saveState='local'`；失败时保留锁并显示错误；验证：新增 App/单元测试用 mock 客户端断言 release 调用与状态文案。
- [x] 4.2 实现 `handleStartEditing`：`acquireLock` 成功后更新 `lockRef/lockHeld` 并触发保存；失败时显示错误；验证：测试断言先 acquire 再 save，lockHeld 恢复。
- [x] 4.3 在 `App.tsx` 把 `onReleaseLock`/`onStartEditing` 传给 `RichEditor`；验证：组件/App 集成测试通过，现有自动 acquire 行为不变。

## 5. Submit new version dialog

- [x] 5.1 在 `App.tsx` 增加 `submitOpen` 状态与 `WorkspaceDialog`：标题 `Submit new version`，正文明确 `not available in this build` / not sent / no approval；footer 提供 Close 与 `Capture browser-local version`；验证：App 测试断言 dialog 文案且不出现 submitted/sent/approved。
- [x] 5.2 `Capture browser-local version` 调用现有 `handleCapture`，成功后关闭 dialog；验证：App 测试断言版本列表/current marker 更新、dialog 关闭。
- [x] 5.3 更新 `web/README.md` 的 footer/提交边界说明；验证：README 可 grep 到 `Submit new version` 与 `browser-local`。

## 6. Integration verification and visual check

- [x] 6.1 更新/新增 e2e：footer 三按钮可见、Release/Start 状态切换、Submit dialog + capture、block-format select、Table 菜单、Comments 占位；验证：`PW_CHANNEL=chrome npm --prefix web run e2e -- --project=desktop --project=narrow` 通过。
- [x] 6.2 运行 `npm --prefix web run typecheck && npm --prefix web run test && npm --prefix web run build` 并修复回归；验证：三条命令退出码为 0。
- [x] 6.3 在 1440×900、1024×800、412×915 对照 mock 检查 footer/toolbar/header/status 带、无横向滚动、English-only；验证：截图结果记录，未通过项不得勾选。

## Workflow follow-up

- Archive this change after the project's review requirements are satisfied.
- Confirm the `document-editor` requirements for footer actions/comments are carried into the main spec.
- 共享提交、审批和评论服务仍由后续独立 change 处理。