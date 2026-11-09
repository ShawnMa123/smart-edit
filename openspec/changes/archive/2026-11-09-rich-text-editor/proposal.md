# Proposal

## Why

编辑器现在是一块纯 textarea（`web/src/components/EditorColumn.tsx`，界面上自己写着 `Plain text · rich text is not implemented`），右上角 `Formatting · not implemented` 也是占位。这带来两个真实后果：

1. **导入的合同"看起来不像合同"了。** 实测 `t1_contract.pdf`（6 页、66 个文本块、3994 字符）：解析没失败、坐标也拿到了，但每个块硬输出一行，于是 `姓名 / 王雪聪等 2 位 / 联系电话 / 办/宅 / 手机 / 13925131801` 这种表格被压成一串孤立行，表头和值配不上对；`委托代订/代办合同`、`协议条款` 这些标题层级、粗体、字号全部消失。DOCX 同理（一个表格单元一块）。
2. **需求 ED-02 是 P0，一直没做。** `Requirements.md` 第 401 行写明：段落、标题、粗体/斜体/下划线、列表、表格、撤销/重做、查找替换，且工具栏状态要与当前选区一致。现在一项都没有。

`editor-shell` 当初选 textarea 是**有理由的**（设计 D3：富文本编辑器会悄悄改写引号/不换行空格，而审计要逐字一致的文本）。所以这件事不能只是"换个控件"：必须同时定义**审计读的那份纯文本从哪来**，否则 AT-01（同输入同输出）与 provenance 检查会一起松动。做完这一点之后，"能看格式"和"审计确定"就不再冲突。

## What Changes

- **中间栏换成富文本编辑器**（TipTap 3 / ProseMirror）：段落、标题 H1–H3、粗体/斜体/下划线、有序与无序列表、表格（含插入/删除行列、表头行）、撤销/重做、查找与替换；工具栏按钮的激活状态跟随当前选区。
- **审计输入 = 投影文本**：新增纯函数 `richToPlainText(doc)`（标题带 `#`、列表带 `- `、表格一行一条 `a | b`），前端上传运行、算快照摘要、判断脏标记都只认这份投影文本；审计后端**完全不变**，仍然只收纯文本、仍然零模型。
- **导入产出富结构**：`POST /stages/parse` 的信封新增 `documents[].rich`（节点树）。DOCX 用 OOXML 确定性映射（`w:pStyle` → 标题级别、`w:b/i/u` → 标记、`w:tbl` → 表格）；PDF 用字号与 `bbox` **启发式**（字号显著更大的块 → 标题；同一水平线的块 → 表格行），并且每条启发式推断在数据里标注 `provenance: "heuristic"`，MUST NOT 冒充确定性结论。
- **版本与快照双存**：`versionStore` 同时保存 rich JSON（用于恢复版面）与投影文本（用于审计与摘要）；恢复旧版本时两者一起恢复。
- **失败与降级不变**：导入的错误语义、OCR 语义、`form` 来源标记全部沿用 `document-import`；富结构转换失败时退回纯文本段落（并标注 `provenance: "fallback"`），不阻断导入。
- **BREAKING（仅内部/前端）**：`EditorColumn` 的 `onChange(text: string)` 契约被 `RichEditor` 的文档模型取代；所有依赖 textarea 的前端测试随之改写。HTTP 契约只做**加法**（`documents[].rich`）。

**不做**：导出 DOCX/PDF（ED-09，下个切片）、字体/颜色/字号面板（ED-02 未要求）、协同编辑、评论与锚点（ED-07）、变量填充、模板编辑页面、图片嵌入、后端存储富文档（无 DB，富文档只在浏览器）。

## Capabilities

### New Capabilities

- `rich-text-editing`: 富文本文档的编辑与呈现——ED-02 的编辑能力集合（段落/标题/粗斜体下划线/列表/表格/撤销重做/查找替换/工具栏与选区同步）、富文档模型与**确定性纯文本投影**、以及"导入的结构化结果如何进入富文档"（确定性映射与启发式推断的标注规则）。

### Modified Capabilities

（无。`document-editor` 属 `editor-shell` 这个未归档 change；它对"纯文本编辑器"的假设与本 change 冲突，需要在那份 delta 里同步，见 `design.md` D9 与 `tasks.md` 的 Workflow follow-up。）

## Impact

- **前端**：`web/package.json` 新增 `@tiptap/react` / `@tiptap/starter-kit` / `@tiptap/extension-table*` / `@tiptap/extension-underline` / 查找扩展；新增 `web/src/rich/`（文档模型、投影、DOCX/PDF→rich 的客户端映射不需要——映射在服务端）；`EditorColumn` → `RichEditor`；`App.tsx` 的 `text`/`dirty`/快照改为"富文档 + 投影"；`versionStore` 存两份；工具栏组件与查找替换面板。
- **后端**：`app/parsing/parse.py` 产出的 `ParsedDoc` 之外新增富结构（**不改** `ParsedDoc` 的冻结字段，富结构放在 `documents[].rich`，由 `app/api/envelope.py` 组装）；`app/state.py` 不动。
- **契约**：信封 `documents[]` 增加可选 `rich`；`POST /runs`、`/stages/*` 的既有语义不变。
- **测试**：投影函数的黄金样例（表格/标题/列表/空段落）、DOCX→rich 映射、PDF 启发式（含"不猜标题级别"的反例）、工具栏与选区同步、查找替换（不得跨标记破坏结构）、以及"投影文本与改造前 textarea 行为一致"的回归。
- **风险**：富文本编辑器改写空白/引号 → 由"审计只认投影文本"隔离，投影规则与黄金样例锁住；TipTap 依赖体积 → 单独 chunk + 构建检查；PDF 启发式误判标题 → 标注 `heuristic` 且不参与审计判定；既有 125 个前端测试大面积触碰 textarea → 分批改写并保持审计相关断言不变。