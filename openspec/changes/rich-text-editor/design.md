# Design

## Context

动机见 `proposal.md`。做决策前必须知道的现状（均已核对）：

| 事实 | 影响 |
|---|---|
| 中间栏是 `<textarea>`（`EditorColumn.tsx`），界面写着 `Plain text · rich text is not implemented` | 换成富文本 = 替换该组件 + 一串前端测试 |
| `App.tsx` 的 `text: string` 同时喂给：编辑器、`createSnapshot`（浏览器 SHA-256）、`createRun`、`createAudit` | 三者都要改成"富文档 + 投影"，否则快照与审计输入会脱节 |
| `versionStore` 存 `{digest, text}` 到 localStorage | 要加 `rich` 一列，且旧版本（只有 text）必须还能读 |
| 导入已产出 `documents[{file_id, filename, form, errors, full_text}]`（`document-import`） | 富结构作**加法**：`documents[].rich` |
| `parse.py`：PDF 块已有 `page` + `bbox`；DOCX 已是 `w:p`/`w:tbl` 结构化遍历 | 两边都够做富结构，但**字号**要额外读（PDF span 的 `size`、DOCX 的 `w:sz`） |
| 审计只收 `{text}`，且要求"同输入同输出"（AT-01）、provenance 要求值能在文本里定位 | 富文本**不得**直接进审计；必须有确定性投影 |
| 前端测试 125 个，其中 `App.test.tsx` / `App.import.test.tsx` / `EditorColumn.test.tsx` 直接操作 textarea | 分批改写，审计相关断言不变 |
| 网络可用（npmmirror），`@tiptap/react` 3.33 可装 | 可以引入成熟框架，不必自研 contenteditable |

## Goals / Non-Goals

**Goals:**

- ED-02 的格式集合真的可用：工具栏、快捷键、表格增删行列、撤销重做、查找替换、工具栏与选区同步。
- **一条投影规则**同时服务审计、快照摘要、版本与脏标记——四处永远一致。
- 导入的 DOCX/PDF 结构进得来，且"确定性 / 启发式 / 退化"在数据里分得清。
- 纯文本场景**行为不变**：粘贴一段纯文本，投影结果与旧 textarea 一致，审计结论一致。

**Non-Goals:**

- 导出 DOCX/PDF（ED-09）、字体/颜色/字号面板、协同、评论锚点（ED-07）、变量、图片嵌入。
- 服务端保存富文档（无 DB）；`/audit/*`、规则包、闸门一律不动。
- 让 PDF 启发式达到"完美还原"——目标是不丢结构、不猜级别、标注来源。

## Decisions

### D1. TipTap 3（ProseMirror）而不是自研 contenteditable

TipTap 提供文档模型、schema 校验、undo/redo、表格与查找扩展，且是 React 友好的 headless 组件（样式我们自己控制，避免把陌生 CSS 塞进现有界面）。**替代方案**：自研 contenteditable（零依赖，但跨浏览器选区/撤销/表格编辑的工作量远超本 change 的收益）；`slate`（模型更自由，但表格与查找要自己拼）。依赖体积用 vite 分包处理（D8）。

### D2. 富文档只在客户端；审计只读投影

```
          +--------------------------- 浏览器 ----------------------------+
 user --> | RichEditor (TipTap doc) --> richToPlainText(doc) --> text     |
          |        |                          |                          |
          |        +--> versionStore(rich)    +--> createSnapshot(text)  |
          |                                   +--> POST /runs {text} ----+--> 后端（不变）
          +-------------------------------------------------------------+
```

**为什么不让后端收富文档**：没有 DB，收了也没处放；而且审计一旦接收结构化输入，`provenance`/`AT-01` 的证明负担会成倍增加。**代价**：格式只在本浏览器有效，刷新/换机器后只剩投影文本——现在本来也是"history stored in this browser"。

### D3. 投影就是规格，先写黄金样例

`web/src/rich/plainText.ts`：

| 节点 | 投影 |
|---|---|
| `heading(level)` | `'#' * level + ' ' + 文本` |
| `paragraph` | 文本（内部 `bold/italic/underline` 标记**丢弃**，只留文字） |
| `bulletList > listItem` | `'- ' + 文本` |
| `orderedList > listItem` | `'1. '`（按序号递增）`+ 文本` |
| `table > tableRow` | 单元格文本用 ` | ` 连接 |
| 块之间 | 单个空行（`\n\n`） |

**为什么丢弃标记**：审计只认文字（`FieldValue.value` 是纯值），`**USD**` 这类标记会给 `charset`/`length` 规则带来噪声。**为什么表格用 ` | `**：它把表头与值的对应关系留在文本里，人读得懂，值仍是子串（provenance 仍能定位）。黄金样例写在测试里（`plainText.test.ts`），改规则必须先改样例。

### D4. DOCX → 富文档：确定性映射

读 `word/document.xml`：`w:pStyle` 的 `val`（`Heading1..3` 或本地化 styleId）→ `heading`；`w:b`/`w:i`/`w:u` → 对应 mark；`w:tbl`/`w:tr`/`w:tc` → `table/tableRow/tableCell`（首行 `tableHeader`）。全部标注 `provenance: "deterministic"`。**不认识的样式一律降级为段落**（不猜级别）。

### D5. PDF → 富文档：启发式，且必须承认是启发式

PDF 没有"标题"这个概念，只有字号与位置：

- **字号**：块内 span 的最大字号 `size`；取全文字号的众数为"正文基准"，`size ≥ 1.3 × 基准` → 候选标题，按字号大小映射到 H1..H3（超过 3 档归 H3）。
- **表格行**：同一页内 `bbox` 垂直中心重叠（|Δy| < 行高一半）的块视为同一行，按 `x0` 排序后用 ` | ` 连接成**一行文本**（富文档里先落为段落，避免凭空造表格）。
- 每条推断带 `provenance: "heuristic"` 与 `reason`（例如 `font_size_1.42x`）；**文字内容一字不改**。
- 无法判断（OCR 文本、无字号、单块）→ 全部段落 + `provenance: "fallback"`。

**为什么不直接造 table 节点**：PDF 没有表格语义，只有位置；凭空造表格会让"这是文件里的表格"变成一句假话。先用"一行一条文本"表达，是否升级成 table 是后续用真实样本再决定的事（写进 Open Questions）。

### D6. 工具栏与选区：只读 `editor.isActive()`

工具栏按钮的 `aria-pressed` 与高亮只来自 TipTap 的 `editor.isActive(mark)` / `editor.isActive('heading', {level})`；**混合选区**（部分加粗）时按 TipTap 语义显示"未完全启用"，不自己算。

### D7. 查找替换：ProseMirror 搜索扩展 + 受控替换

查找/替换用 ProseMirror 的文本搜索（遍历 text 节点、保留 marks），替换单个/全部时**只改命中的文字节点**，绝不重建整段——否则用户刚设置的格式会被清掉。查找面板展示当前命中序号 / 总数，关闭后清除高亮。

### D8. 依赖与体积

新增依赖集中在同一个 chunk，`npm --prefix web run build` 后检查主 chunk 是否仍在可接受范围（记录实测值到 `DEMO.md`）；若过大，编辑器按路由/交互懒加载（`React.lazy`）。

### D9. 与 `editor-shell` 的冲突要显式处理

`editor-shell` 的 `document-editor` delta 现在写着"plain textarea on purpose（设计 D3）"与 `Formatting · not implemented`。本 change 落地后那两处**变成错的**。处理方式：在本 change 的 `Workflow follow-up` 里记一条，由 `editor-shell` 的所有者同步其 delta；本 change 不改别人的 spec。

### D10. 兼容与回退

- 旧的 `versionStore` 条目只有 `text`：读到时按"单段落富文档"渲染（`text.split('\n\n')`）。
- 信封里没有 `documents[].rich`：把 `full_text` 当单段落文档（旧行为）。
- 富结构转换抛错：导入仍成功，`rich` 标 `fallback`，面板文案说明"格式未还原"。
- 若 TipTap 初始化失败（极端环境）：降级为 `textarea`（保留旧行为），并在界面说明——不允许白屏。

## Risks / Trade-offs

- **[富文本会改写空白/引号]** → 审计只认投影文本，而投影由我们定义；`richToPlainText` 有黄金样例，且"纯文本粘贴 → 投影 → 审计"结论与改造前一致的回归测试守着。
- **[投影丢失标记信息]** 用户加粗的内容在审计文本里看不出加粗 → 可接受：审计判断的是值，不是排版；报告里的 `evidence` 仍指向原文片段。
- **[PDF 启发式误判标题]** 一个 17pt 的电报表头被当 H2 → 标注 `heuristic` + 人可在编辑器里改；不参与任何审计判定。
- **[表格在 PDF 里被压成一行文本]** 信息比原始版式少，但表头与值对得上（这就是 L1 的收益）；升级为真 table 见 Open Questions。
- **[依赖体积与安全]** TipTap 引入约十个包 → 分包 + 锁定版本；它们只在 `web/`，不进后端依赖树。
- **[前端测试大面积改写]** 125 个测试里操作 textarea 的那些要改 → 分批：先加 `RichEditor` 与投影测试，再替换组件，最后改 App 级测试；审计相关断言保持原样。
- **[格式与"已确认"解锁]** 有人会以为"排好版 = 数据可信" → OCR/`inferred` 的语义完全不变（`bind.py` 未动），并且 spec 里有"格式不改变判定"的场景。

## Migration Plan

1. **投影先行**：`rich/plainText.ts` + 黄金样例 + "纯文本回归"测试；此时不碰 UI。
2. **富结构进信封**：服务端 `documents[].rich`（DOCX 确定性、PDF 启发式、失败 fallback）；后端既有测试不变（`rich` 是可选的）。
3. **替换编辑器**：`RichEditor` + 工具栏 + 表格 + 查找替换；`App.tsx` 改用富文档 + 投影；`versionStore` 双存 + 兼容旧条目。
4. **回归与演示**：用 `t1_contract.pdf` 与 `fixtures/imports/guarantee.docx` 做端到端；写 `DEMO.md`。
5. **回滚**：删掉 `web/src/rich/` 与 TipTap 依赖、恢复 `EditorColumn` 的 textarea、忽略 `documents[].rich`，即回到今天的行为（后端可保留 `rich` 而不影响任何人）。

## Open Questions

1. **PDF 的表格要不要升级成真 table 节点**（现在先压成"一行一条文本"）。需要更多真实样本判断误判率；升级只影响富文档构造，不影响投影契约。
2. **有序列表的投影编号**：现在是 `1. 2. 3.` 顺序展开还是全用 `1.`？黄金样例里先按顺序展开（更像原文），若要"MUST 保持原编号"需再确认。
3. **多级列表/嵌套列表**的缩进投影规则（本 change 只做单级）。
4. **`editor-shell` 的 delta 由谁同步**（D9）——需要该 change 的所有者改它自己的规格。
5. **导出**（ED-09）与富文档的关系：导出的是富文档还是投影文本？留给导出那个 change。