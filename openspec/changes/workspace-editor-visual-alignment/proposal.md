# Proposal

## Why

当前工作区结构已接近参考原型，但编辑区缺少最影响观感的动作层：mock 在页面底部有 `Release lock / Start editing / Submit new version`，当前只有字符数与说明文字；文档头还保留过时的 `Formatting · Not available` 并缺少 `Comments`；工具栏 H1/H2/H3、表格操作全部平铺，状态带也比 mock 更重。结果是页面“功能在”，但看起来仍像工程控制台。

这次 change 只做编辑区与文档头的视觉/交互对齐，不新增后端能力，不复制 HSBC 品牌或中文 chrome，也不伪造共享版本提交。

## What Changes

- 编辑器 footer 增加动作条：
  - `Release lock` 调用现有锁释放接口；
  - `Start editing` 重新获取编辑锁；
  - `Submit new version` 保留主按钮位置，点击打开明确说明“本构建没有共享版本提交”的对话框，并提供真实的 `Capture browser-local version`。
- 文档头动作行：
  - 移除过时的 `Formatting · Not available`；
  - 增加 `Comments` 入口，打开明确的 Comments 占位；
  - 保留 `Import file` 真实主操作，`Export` / `Start approval` 继续明确不可用。
- 编辑器工具栏降低密度：
  - H1/H2/H3/Paragraph 收进 block-format 选择器；
  - 表格行/列操作收进 `Table` 二级菜单，保留 `Insert table`；
  - 保留 B/I/U、列表、撤销重做、Find、Variables 与键盘快捷键。
- 编辑状态带压缩为一行 lock-line 风格，继续显示 snapshot、draft revision、lock 与 save 状态；字符数仍留在 footer。
- 调整文档头 title/间距、footer 动作按钮、状态 chip 与工具栏的样式，使层级更接近参考原型。
- **BREAKING**: 无后端或数据契约破坏；编辑器 footer 与文档头动作布局变化。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-editor`: 增加编辑区 footer 的锁/提交动作与不可用提交的诚实降级；文档头增加 Comments 入口并移除过时的 Formatting 不可用动作。

## Impact

- 前端：`web/src/components/RichEditor.tsx`、`web/src/components/DocumentActions.tsx`、`web/src/App.tsx`、`web/src/styles.css`，可能新增 `DocumentSubmitDialog` 或复用 `WorkspaceDialog`。
- 前端 API：复用已有 `acquireLock` / `releaseLock`，不新增后端接口。
- 测试：更新 `RichEditor.test.tsx`、`DocumentActions.test.tsx`、`App.test.tsx`，新增提交对话框与锁动作覆盖。
- 不涉及：HSBC/中文品牌、真实共享版本提交、审批工作流、评论服务、导出适配器、后端 API/数据库。