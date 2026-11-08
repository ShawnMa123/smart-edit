# Tasks

> 依据：`proposal.md`（范围 ED-02 全量）、`specs/rich-text-editing/spec.md`（要求）、`design.md`（做法 D1–D10）。
> 每组自带该组的测试与文档；第 7 组只做集成验收。**审计后端不在本 change 的改动范围内。**

## 0. 投影先行（不碰 UI，先锁住契约）

- [ ] 0.1 `web/src/rich/richDocument.ts`：定义富文档的最小节点类型（`document/heading/paragraph/text/list/table`，含 marks 与可选 `provenance`）。Verify: 单测断言类型守卫拒绝未知节点，且默认空文档合法。
- [ ] 0.2 `web/src/rich/plainText.ts`：`richToPlainText(doc)` 按 D3 规则投影（标题 `#`、列表 `- `/`1. `、表格 ` | `、块间单个空行、marks 丢弃）。Verify: **黄金样例**覆盖标题三级 / 有序无序列表 / 表格 / 空段落 / 只有格式无文字；同一文档两次投影相等。
- [ ] 0.3 纯文本回归：把一段纯文本（含多个空行）包成"单段落富文档"投影。Verify: 断言投影结果与改造前 textarea 提交的文本一致（用 `fixtures/llm/sample_document.txt` 做样例），并断言快照摘要相同。

## 1. 富结构进信封（服务端，只做加法）

- [ ] 1.1 `app/api/envelope.py`：`documents[]` 增加可选 `rich`（无富结构时省略）。Verify: 既有 API 测试全绿；新增测试断言缺少 `rich` 时客户端路径仍可用。
- [ ] 1.2 `app/parsing/rich_docx.py`：DOCX → 富文档（`w:pStyle`→标题、`w:b/i/u`→marks、`w:tbl`→表格，首行表头），全部 `provenance: "deterministic"`；未知样式降级为段落。Verify: 单测用含标题/粗体/表格的最小 docx，断言节点结构与 provenance；断言未知样式**不猜级别**。
- [ ] 1.3 `app/parsing/rich_pdf.py`：PDF → 富文档（字号众数为基准、≥1.3× 视为候选标题并映射 H1–H3、同行按 `bbox` 聚类并用 ` | ` 连成一行文本），全部 `provenance: "heuristic"` 带 `reason`；文字内容一字不改。Verify: 单测用两个假页（一个含大字号块、一个全同字号）分别断言"推断为标题"与"全部段落"；断言改动前后 `full_text` 完全一致。
- [ ] 1.4 失败与退化：转换抛错 → `rich` 标 `fallback` 且导入仍成功；OCR/纯文本来源 → 全部段落 + `fallback`。Verify: 单测用"必抛"的 stub 与一张 OCR 文档，断言导入结果、`form` 与 `errors` 均不受影响。

## 2. 编辑器落地（TipTap）

- [ ] 2.1 依赖与骨架：`@tiptap/react` / `starter-kit` / `table` / `underline` + 查找扩展；`web/src/components/RichEditor.tsx` 渲染文档，`onChange(richDoc)`。Verify: 组件测试断言渲染标题/列表/表格；`npm run build` 通过并记录 chunk 体积。
- [ ] 2.2 工具栏：段落/三级标题/粗体/斜体/下划线/两种列表/表格插入与增删行列/撤销/重做；`aria-pressed` 来自 `editor.isActive()`。Verify: 组件测试逐个按钮作用于选区；混合选区时标记**不**显示为完全启用。
- [ ] 2.3 查找与替换：命中高亮、上一处/下一处、替换单个/全部。Verify: 测试断言替换只改命中文字且**保留原有 marks**；关闭面板后高亮清除。
- [ ] 2.4 降级：TipTap 初始化失败时回退 textarea 并说明原因。Verify: 测试用抛错的编辑器工厂断言回退渲染且可继续输入。

## 3. 接入应用（快照 / 版本 / 导入）

- [ ] 3.1 `App.tsx`：以富文档为状态源，`text` 一律由 `richToPlainText` 派生（编辑器、快照、`createRun`、审计共用这一份）。Verify: App 测试断言"改格式不改文字时，快照摘要不变"与"改文字时摘要变化"。
- [ ] 3.2 `versionStore`：条目加可选 `rich`，旧条目（只有 `text`）可读并按单段落渲染。Verify: 单测覆盖"保存富版本→恢复富版本"与"读旧条目"。
- [ ] 3.3 导入接线：拿到 `documents[].rich` 就渲染富文档（标注 `heuristic`/`fallback` 时在面板提示"格式可能未完全还原"）；没有 `rich` 时把 `full_text` 当单段落。Verify: 组件测试覆盖三种情形；断言失败文件仍不可用。
- [ ] 3.4 脏标记与捕获：`dirty` 以投影文本与最后一次捕获的投影比较。Verify: 测试断言"只改格式不算未保存"（按 D3 投影确实可能不变）。

## 4. 诚实性不变（回归护栏）

- [ ] 4.1 格式不改变判定：同一段文字加粗/设为标题后跑审计，结论不变。Verify: 组件 + 视图测试断言 `auditView` 的 outcome/覆盖率与改造前一致。
- [ ] 4.2 OCR 文本仍待核实：导入 OCR 文本并格式化后，抽取字段仍 `inferred`。Verify: 测试断言字段状态与 `needs_input` 行为不变。
- [ ] 4.3 空文档：清空编辑器后 `richToPlainText` 为 `''`，提交按空提交处理。Verify: 测试断言不会发出 `{text: ''}` 的"成功"请求。

## 5. 文档

- [ ] 5.1 `how_to_use.md`：新增"富文本编辑"一节（工具栏、快捷键、表格增删行列、查找替换、为什么审计只读投影文本）。Verify: 文档里每条操作都能在界面找到对应控件。
- [ ] 5.2 `web/README.md`：更新中间栏说明（不再是纯文本），补 TipTap 依赖与降级路径。Verify: 与实现一致，且删掉"rich text is not implemented"的表述。

## 6. 端到端与演示

- [ ] 6.1 真实样本：`t1_contract.pdf`（6 页、66 块）导入后，标题层级与表格行可读；`fixtures/imports/guarantee.docx` 的标题/粗体/表格按确定性映射还原。Verify: `scripts/` 或 vitest e2e 记录两者导入后的节点统计（标题数/表格行数）与投影文本片段。
- [ ] 6.2 端到端审计不变：用改造后的编辑器粘贴 `fixtures/llm/sample_document.txt`，`Run spec audit` 的输出与改造前逐项一致。Verify: `web/src/e2e.audit.test.ts` 增加一条"富文本 → 投影 → 审计"的用例并通过。
- [ ] 6.3 写 `openspec/changes/rich-text-editor/DEMO.md`：命令、实测的 chunk 体积、`t1_contract.pdf` 与 docx 的还原统计、投影样例、以及"格式不改变审计判定"的实测。Verify: 数字与 6.1/6.2 的实际输出一致。

## 7. 集成验收

- [ ] 7.1 全量回归：Python 347 + 前端（改造后数量）全绿；`npm run typecheck` 与 `npm run build` 通过。Verify: 记录最终数字到 `DEMO.md`。
- [ ] 7.2 纯文本用户不受影响：粘贴纯文本 → 捕获版本 → 审计，三步行为与改造前一致。Verify: 手工走一遍并记录输出（与 `how_to_use.md` §3 的期望值对照）。

## Workflow follow-up

- `editor-shell` 的 `document-editor` delta 里"plain textarea on purpose"与 `Formatting · not implemented` 与本 change 冲突（D9）：需由该 change 的所有者同步其规格，本 change 不改别人的 delta。
- 导出（ED-09）应作为独立 change：先决定"导出富文档还是投影文本"，见 `design.md` Open Questions 5。
- PDF 表格是否升级为真 table 节点（Open Questions 1）与多级列表缩进（Open Questions 3）留给有真实样本后的细化。
- 若后续要服务端保存富文档（跨设备），那是存储层的 change，会同时影响快照与版本语义。
- 本 change 不改审计后端；`app/rules/`、`app/audit/` 的零模型承诺继续由既有 purity 测试守着。