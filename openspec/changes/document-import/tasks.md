# Tasks

> 依据：`proposal.md`（范围）、`specs/document-import/spec.md`（要求）、`design.md`（做法 D1–D28）、
> `TBD-image-recognition.md`（明确暂缓的视觉模型路线）。
> 每组自带该组的测试与文档；第 6 组只做跨组集成与验收。
>
> **状态（2026-11-09）：** 第 0–6 组已完成并上线（21/21）。**第 7–9 组是第二轮**（PDF 版面保真，14/14 已完成），
> 因客户实测 `guarantee-and-standby-letters-of-credit-wording.pdf` 指出"格式不像 PDF 原样"而加入。
> 原第一版方案曾建议"删掉页脚与页码"，现已按客户要求改为**保留原样**（design D15）。
> **第 10–12 组是第三轮**（PDF 视觉行，10/10 已完成）：Contents 页的页码被拆到下一行，根因是 `line` ≠ 视觉行
> （138/717 个 block 受影响）；做法见 design D17–D20，Non-Goals 见 proposal。
> **第 13 组是第四轮**（PDF 布局保真，6/6 已完成）：`Beneficiary:` 后面的下划线是矢量线，已读取并显示；
> 目录/页码已右对齐。做法见 design D21–D24。
> **第 14 组是第五轮**（可填写空白与光标稳定，0/6 未完成）：用户在下划线处输入时光标跳到文末、无法落点。
> 根因是 `useRichEditor` 的回声 `setContent` 与 `pdfGap` 的原子模型；做法见 design D25–D28。

## 0. 契约与签字（最先做，且只做加法）

- [x] 0.1 `app/state.py`：`ParsedDoc.form` 增加两个取值 `docx_text`、`image_ocr`（保留现有四个）。Verify: `git diff` 只改这一行；所有既有测试全绿；改动记录写进本文件（与 `agent-audit` 0.2 同一套签字流程）。

  **改动记录（2026-11-09）**：`ParsedDoc.form` 的字面量由 4 个取值扩到 6 个，**没有**改动任何字段、类型或既有取值；
  这是一个"拓宽枚举"的加法，现有代码与数据完全不受影响。A 在采纳本 change 时批准；B / C 追认待签——
  他们若反对，回滚方式是把字面量改回 4 个取值并删除 DOCX/OCR 两个分支（`app/parsing/parse.py`），
  不影响其他任何模块。证据：`tests/test_parse_import.py`、`tests/test_api.py::test_the_envelope_carries_the_imported_documents`。

  **归档批准（2026-11-09）**：项目所有者 Andy 明确批准归档（"我同意"）：确认这是纯加法——6 个取值中既有 4 个不变，
  无字段、类型或行为回退。B / C 的追认仍待签；与 `agent-audit` 0.2 的口径一致——改动只拓宽冻结枚举、不影响任何
  既有数据，追认不阻塞归档；若 B / C 事后反对，回滚步骤同上。
- [x] 0.2 `app/api/envelope.py`：新增 `documents` 键 `[{file_id, filename, form, errors, full_text}]`，未解析时为 `[]`。Verify: `TestClient` 测试断言未解析运行返回 `[]`、解析后字段齐全，且既有 10 个键与 `INCOMPLETE_RESULT` 语义不变。

## 1. DOCX 解析（零新依赖）

- [x] 1.1 `app/parsing/parse.py`：`_form_for` 认识 `.docx` / `application/vnd.openxmlformats-officedocument.wordprocessingml.document` → `docx_text`；旧的二进制 `.doc` 仍走 `unsupported_mime`。Verify: 单测覆盖两种 MIME 与 `.doc` 的拒绝。
- [x] 1.2 `_blocks_from_docx()`：标准库 `zipfile` + `xml.etree` 按文档顺序抽 `w:p` 与 `w:tbl/w:tc` 文本，输出 `ParsedBlock`（`page`/`bbox` 为 `None`，表格单元用 `kind="table_cell"`）。Verify: 单测用最小 docx（含 2 段 + 1 张 1×2 表格）断言块顺序与文本；`full_text` 与块顺序一致。
- [x] 1.3 失败与安全：缺 `word/document.xml`、损坏压缩包、含 `vbaProject.bin` 三种情形。Verify: 前两种 → `errors=["docx_unreadable: …"]` 且 `full_text==""`；第三种仍能抽出正文且**不执行**任何嵌入内容（测试断言不产生副作用、不 import 任何办公库）。

## 2. 本地 OCR（pymupdf + 系统 tesseract）

- [x] 2.1 `_form_for` 认识 `image/png`、`image/jpeg`（含扩展名）→ `image_ocr`；`parse_file` 增加图片分支：`pymupdf.open(path)` 后对第 1 页 OCR。Verify: 单测注入 stub textpage，断言 `blocks` 带图片坐标 `bbox`、`form=="image_ocr"`。
- [x] 2.2 扫描版 PDF 回退：文本层为空且页数在上限内 → 逐页 OCR（`page` 指向真实页码）；超过 `MAX_OCR_PAGES` → `errors=["too_many_pages"]`。Verify: 两个单测（可 OCR 的假扫描件 / 超页数拒绝），断言 `form`、块页码与错误码。
- [x] 2.3 引擎缺失语义：OCR 调用抛错且指向 tesseract/tessdata → `errors=["ocr_engine_missing: …"]`，不崩、不返回空成功。Verify: 单测用"必抛"的 stub 断言错误码与 `full_text==""`，并断言阶段报告为 `partial`/`failed` 而非 `done`。
- [x] 2.4 识别为空的语义：OCR 成功但无文字 → `errors=["no_text_recognized"]`；打不开的图片 → `image_open_failed`。Verify: 两个单测各断言错误码，且都不产生 `full_text`。
- [x] 2.5 语言与 dpi 可配置：`SMART_EDIT_OCR_LANGS`（默认 `chi_sim+eng`）、`OCR_DPI`（默认 300）；`MAX_BYTES` / `MAX_OCR_PAGES` 作为常量模块的显式配置。Verify: 单测断言默认值与覆盖生效；超字节 → `file_too_large`。

## 3. 解析聚合与阶段报告

- [x] 3.1 `app/nodes/parse.py`：新错误码下仍产出正确的 `partial`/`failed`，`reason` 里点名失败文件（不泄露内部异常栈）。Verify: 单测覆盖"1 成功 + 1 引擎缺失"→ `partial` 且原因含文件名；"全部失败"→ `failed`。
- [x] 3.2 既有行为不回退：无文本层的 PDF 不再直接 `no_text_layer`（改走 OCR），但**纯文本运行**（`text/plain`）与 `docs` 复用的行为必须完全不变。Verify: 既有 `tests/test_parse.py` 全绿 + 新增一条"txt 路径未调用 OCR"的断言。

## 4. 前端上传与填入编辑器

- [x] 4.1 `web/src/api/client.ts`：`createRunWithFiles(files)`（`FormData`，`POST /runs`）；`web/src/api/types.ts` 增加 `documents` 类型。Verify: `client.test.ts` 断言 multipart 请求形状与 URL；类型检查通过。
- [x] 4.2 `DocumentActions`：`Import file` 从占位变成真按钮（隐藏 `<input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg">`），并从 `UNAVAILABLE_ACTIONS` 移出。Verify: 组件测试断言按钮可点、选中文件后调用上传、`accept` 属性正确，且其余"not implemented"条目仍保留。
- [x] 4.3 导入结果面板：上传 → `parse` → 展示逐文件结果（成功/失败原因、`form`）；"文本识别自 …，请核对"横幅（`image_ocr` 时）；多个成功让用户选一个；失败提供"重新上传 / 从空白继续"。Verify: 组件测试覆盖三种情形；断言没有任何路径把失败显示成成功。
- [x] 4.4 填入编辑器：用户选定文档后把 `full_text` 写入中间栏，且**不**覆盖用户已编辑的内容（有未保存编辑时先确认）。Verify: 组件测试断言 textarea 内容、以及"已有编辑时弹出确认"。

## 5. 文档与演示

- [x] 5.1 `how_to_use.md` 增加"从文件导入"一节：系统依赖（`brew install tesseract tesseract-lang`）、支持的类型、失败怎么办、OCR 文本为何"待核实"。Verify: 照文档命令逐条执行可复现（引擎缺失时给出文档里描述的那条错误）。
- [x] 5.2 `web/README.md` 补上传入口与三条新错误码的用户可见文案。Verify: 文档中每条错误码都能在 UI 上找到对应文案。

## 6. 集成与验收

- [x] 6.1 端到端（真实 HTTP）：上传一份 DOCX → `parse` → 读 `documents` → 文本非空且 `form=="docx_text"`；上传一张图片（引擎可用时）→ `form=="image_ocr"`；引擎不可用时 → `partial` + `ocr_engine_missing`。Verify: `web/src/e2e.import.test.ts`（`VITE_E2E=1`）覆盖三条，日志记录实测输出。
- [x] 6.2 回归：不传文件的既有路径（粘贴文本 → normalize → audit）行为与今天完全一致。Verify: 既有 330 个 Python 测试 + 109 个前端测试全绿。
- [x] 6.3 写 `openspec/changes/document-import/DEMO.md`：命令、系统依赖、实测的四种输入结果（含失败样例）、以及"OCR 文本为何仍需人工确认"的声明。Verify: 文件存在且数字/状态与 6.1 输出一致。

## 7. PDF 版面保真（第二轮，2026-11-09）

- [x] 7.1 `app/parsing/rich_pdf.py`：层级改为**字号排名**（去重降序：最大 → H1、次之 → H2、再 → H3，正文不入级），正文基准仍取出现次数最多的字号。Verify: 单测用 4 档字号（48/20/14/9）断言"封面 H1、章节 H2、副标题 H3、正文段落"；再断言"只有一种字号 → 0 个标题"。
- [x] 7.2 书签优先：若 `doc.get_toc()` 非空，按书签 `title` + 页匹配块并决定层级，匹配不到的块退回字号排名。Verify: 用带书签的 PDF 断言层级来自书签、`provenanceNote` 写明来源；用无书签的断言退回字号排名。
- [x] 7.3 粗体/斜体从 span `flags` 与字体名（`Bold`/`Black`/`Heavy`、`Italic`/`Oblique`）取"或"写入 marks。Verify: 单测构造粗体 span 断言 `marks` 含 `bold`；断言普通字体不产生 marks；断言加粗前后**投影文本完全相同**。
- [x] 7.4 显示属性：每个块带 `attrs: {fontSize, fontFamily, page}`。Verify: 单测断言 9pt Helvetica 的块带这两个属性；断言缺少属性时编辑器仍渲染（前端测试）。
- [x] 7.5 页边界：相邻块 `page` 变化处插入 `{"type": "pageBreak"}`。Verify: 单测断言 3 页文档恰好 2 个 `pageBreak`；断言 `richToPlainText` 忽略它（字符数不变）。
- [x] 7.6 页码/页脚**保留**且不与正文粘连：页码为独立段落、页脚为所在页最后一块。Verify: 单测断言纯数字块仍在、页脚块仍在，且都不与相邻正文合并。
- [x] 7.7 守恒与逐字：`rich` 块数等于解析块数（`pageBreak` 另计），文字逐字相同（含 `\xa0`）。Verify: 单测把 `rich` 投影回来，忽略 `pageBreak` 与块间隔符，断言字符序列与 `full_text` 一致。

## 8. 前端渲染保真（第二轮）

- [x] 8.1 `RichDocument` 类型与 TipTap schema 支持 `fontSize` / `fontFamily` / `page` 可选属性与 `pageBreak` 节点；`richToPlainText` 忽略它们。Verify: 投影黄金样例新增"含属性与 pageBreak 的文档投影不变"；schema 校验通过。
- [x] 8.2 编辑器按属性渲染：段落/标题使用 `font-size`、`font-family` 内联样式；`pageBreak` 渲染为分隔线（可在编辑器里删除，但不产生文字）。Verify: 组件测试断言内联样式与分隔线存在；断言导入 25 页 PDF 后块数与页边界数正确。
- [x] 8.3 导入提示：面板显示 `provenance` 与"层级来自书签/字号、N 页、K 个页边界"。Verify: 组件测试断言文案随 `provenanceNote` 变化。

## 9. 验收（第二轮）

- [x] 9.1 真实样本回归：`fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf`（25 页）——断言层级数分布为 H1=1 / H2=23 / H3=1、粗体数量 > 0、`pageBreak` = 24、文本块数 = 715（另 24 个页边界，共 739）、投影与 `full_text` 逐字一致。Verify: pytest/HTTP e2e 记录实测数字到 `DEMO.md`。
- [x] 9.2 旧行为不变：`fixtures/imports/guarantee.docx` 的既有断言仍成立（仍 `deterministic`）；扫描版 PDF 仍 `heuristic`；`tests/test_rich_mapping.py` 的既有 PDF 用例全绿（`t1_contract.pdf` 已不在仓库，见 `DEMO.md`「一处样本变动」）。Verify: 既有测试全绿。
- [x] 9.3 审计不受影响：同一文本只改字号/粗体/页边界后，审计 counts/outcome 不变。Verify: `tests/test_rich_honesty.py` 扩充一条"含 pageBreak 与字体属性"的用例。
- [x] 9.4 更新 `DEMO.md`：加入这份 25 页样本的实测（层级分布、粗体数、页边界数、与 `full_text` 的逐字一致性），并说明"我们保留页码与页脚"这一口径。Verify: 数字与实际输出一致。

## 10. 共享视觉行层（第三轮，纯函数，先锁规则）

- [x] 10.1 新增 `app/parsing/pdf_layout.py`：`visual_rows(block)` 按"垂直区间交集 > 较矮者高度的 50%"把同一 block 内的 `line` 归并为行；行按 `y`、行内片段按 `x` 排序。Verify: 单测用合成 block 覆盖"同带两段 → 1 行"、"上下两行 → 2 行"、"单行"、"重叠 49% 不算同行"。
- [x] 10.2 `row_fragments(row)` / `block_text(block)`：每个非空片段去掉首尾空白后用**一个空格**连接，空片段跳过；行与行之间保留 `\n`。Verify: 单测断言 `'Tender Guarantee Standard\x08'` + `'4'` → `Tender Guarantee Standard 4`；两行仍是两行。
- [x] 10.3 控制字符在共享层规范化：`\x07`、`\x08` 移除，`\t` → 一个空格，`\xa0` 与全角空格原样保留。Verify: 单测逐字符断言这三类输入。

## 11. 解析层与富文本层接入（第三轮）

- [x] 11.1 `app/parsing/parse.py::_blocks_from_pdf` 从 `get_text("blocks")` 改为 `get_text("dict")` + `block_text`；错误路径、大小/页数上限、`page`、`bbox`、`form` 全部不变。Verify: `tests/test_parse.py`、`tests/test_parse_import.py` 全绿；fixture 块数仍为 715。
- [x] 11.2 更新这份 25 页样本的期望并断言：`full_text` **50799 → 50022** 字符、换行 **915 → 735**；第 3 页出现 `Tender Guarantee Standard 4` 与 `Facility Guarantee 15`；第 4 页填空句为一行；`full_text` 不含 `\x07`/`\x08`/`\t` 且 `\xa0` 仍存在。Verify: `tests/test_import_acceptance.py` 的具体断言。
- [x] 11.3 `app/parsing/rich_pdf.py::_text_nodes` 改为 row → fragment → span：marks 仍按 span 保留，行内空格、行间 `\n`；`_block_size` / `_is_uniform` / `_heading_ranks` / `_toc_level_for` 不变。Verify: `tests/test_rich_pdf_fidelity.py` 全绿；投影与 `full_text` 逐字相等；块数 715、`pageBreak` 24、标题 H1=1/H2=23/H3=1、粗体 75 不变。
- [x] 11.4 其他文本路径不受影响：DOCX 仍 `deterministic`、纯文本路径未调用 PDF 行规则、OCR 分支未改。Verify: `tests/test_rich_mapping.py`、`tests/test_parse_import.py` 全绿。

## 12. 第三轮验收与记录

- [x] 12.1 审计不受影响：同一文本在行重组后 `counts` / `outcome` 不变（含 pageBreak 与字体属性的用例）。Verify: `tests/test_rich_honesty.py` 全绿。
- [x] 12.2 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`npm --prefix web run build` 全部通过并记录数字。Verify: 命令输出与记录一致。
- [x] 12.3 更新 `DEMO.md`：加入第三轮的修前/修后（块数、字符数、换行数、目录/填空样例）与"只保证同行、不做右对齐/保宽"的口径。Verify: 文件中的数字与实际输出一致。

## 13. PDF 布局保真（第四轮）

- [x] 13.1 `app/parsing/rich_pdf.py` + `pdf_layout.py`：从 `page.get_drawings()` 过滤水平线（宽 > 20pt、高 < 1.5pt），只关联到**单视觉行** block（线 y 在行带 ±3pt、x 与行相交或紧邻 ≤40pt；与文字 x 覆盖的线跳过）。Verify: 单测覆盖"水平线 / 竖线 / 页眉分隔线"过滤、行带关联、多行 block 不处理；fixture 统计 226 条线、171 个带线行（另有 24 个页眉分隔线被排除）、0 个多行布局 block。
- [x] 13.2 `rich_pdf` 生成显示用 `pdfGap` 节点：片段之间 / 行首 / 行尾的可见下划线（`rule=true`）与不可见间距（`rule=false`），`grow` 按 PDF 宽度；单行 block 加 `row=true`。Verify: 第 5 页 `Beneficiary:` 后有可见 gap、占位符行有行首可见 gap；第 3 页目录有不可见 gap；投影仍逐字等于 `full_text`，715 块 / 50022 字符 / 24 页边界不变。
- [x] 13.3 右对齐：目录页码通过不可见 gap 到右边界；单片段贴右边界的 block（26 个：24 个页码 + `Page` + 一个占位符）加 `align="right"`。Verify: 第 3 页 `Tender Guarantee Standard` 的页码在右边界；第 2 页 `2`、第 3 页 `Page` 右对齐；投影不变。
- [x] 13.4 前端模型与 schema：`richDocument.ts` 增加 `pdfGap` 内联节点与 `row` / `align` 属性；`tiptap.ts` 注册原子节点与全局属性；`plainText.ts` 忽略 gap；`styles.css` 增加 flex 行、下划线、右对齐。Verify: `npm run typecheck` clean；`richToPlainText` 对含 gap 的文档投影不变。
- [x] 13.5 前端渲染测试：编辑器显示 `Beneficiary:` 下划线、目录页码在右边界、旧文档无变化；`pdfGap` 不产生字符、不可选。Verify: `RichEditor.test.tsx` / `plainText.test.ts` 新增用例；既有前端测试全绿。
- [x] 13.6 验收与记录：真实样本断言第 5 页 Beneficiary / 占位符、第 3 页目录、第 22 页、页码；715 块 / 50022 字符 / 24 页边界、投影 == `full_text`、审计 counts/outcome 不变；全量 pytest / web / typecheck / build；更新 DEMO 第四轮。Verify: 命令输出与 DEMO 数字一致。

## 14. 可填写空白与光标稳定（第五轮）

- [x] 14.1 `useRichEditor` 回声守卫：把 `applied` ref 前移，在 `onUpdate` 里先 `applied.current = next` 再 `onChange(next)`；effect 只在外部导入/恢复（`applied.current !== document`）时 `setContent`。Verify: 受控 React harness 或 Playwright 在中部连续键入后选区不跳；导入/恢复仍能替换内容。
- [x] 14.2 `pdfGap` 可编辑内容模型：`richDocument.ts` 增加 `content?: TextNode[]`；`tiptap.ts` 改为 `atom: false`、`content: 'text*'`、`renderHTML` 保留内容洞；空/旧 gap 仍渲染为空下划线。Verify: headless Editor 在 gap 内插入文字后 `getJSON` 保留 content；空 gap 渲染不变；`npm run typecheck` clean。
- [x] 14.3 投影与审计：`plainText.ts` 对空 gap 投影 `''`、对填入值投影其文字，并在文字↔gap 边界按需补一个空格；`full_text` 不变。Verify: `richToPlainText` 断言 `Beneficiary:`（空）与 `Beneficiary: ACME Trading`（填）；审计 `counts`/`outcome` 在空导入时不变、填入后包含该值。
- [x] 14.4 交互与样式：点击下划线把光标放进 gap（必要时 NodeView/`handleClick`）；`flex` 宽度、`min-width`、`border-bottom`；空 gap 可见可点。Verify: 组件/浏览器测试断言 gap 可编辑、光标落点与宽度；`styles.css` 更新。
- [x] 14.5 真实样本验收：第 5 页 `Beneficiary:` 的 gap 填入 `ACME Trading`，投影为 `Beneficiary: ACME Trading`，光标不跳到文末；空导入仍 50022 字符 / 715 块 / 24 页边界。Verify: pytest / 前端 / E2E 记录。
- [x] 14.6 全量回归与 DEMO：`pytest -q`、`npm test`、typecheck、build；更新 `DEMO.md` 第五轮（光标 bug、可填写空白、填入值进入审计）。Verify: 命令输出与 DEMO 数字一致。

## Workflow follow-up

- **跨 change 一致性（第二轮）**：`rich-text-editor` 的 `rich-text-editing` spec 只覆盖了"投影与渲染现有结构"，
  本轮的 `fontSize` / `fontFamily` / `page` 可选属性与 `pageBreak` 节点属于**新增渲染能力**，需由那个 change 的所有者
  在它的 delta 里补一条（本 change 不改别人的规格）。**2026-11-09 已完成**：该 delta 新增
  "富文档可携带显示属性与页边界"要求（3 个 scenario）。
- `ParsedDoc.form` 的两个新取值需要在归档前记录批准（与 `agent-audit` 0.2 同一张签字表）；未签字前不得把本 change 归档。
- `editor-shell` 的 `document-editor` delta 把 "file import" 列为"present but marked not implemented"；本 change 落地后需要在那份 delta 里同步（改它自己 change 的规格，不是本 change 的）。**2026-11-09 已完成**：该 delta 已按实际能力区分 file import / formatting（可用）与 export / approval（仍不可用）。
- **可填写空白（第五轮，2026-11-09 已纳入）**：见第 14 组与 design D25–D28；结构化字段/自动抽取仍是 follow-up。真正的 `<input>` NodeView 若需要，见 Open Questions 10。
- **跨 block 表格行**：第一轮的 ` | ` 行为等有真实表格样本时单独提 change；第三轮明确只做 block 内。
- **OCR 路径行重组**：`_blocks_from_pdf_ocr` 仍用 blocks 模式；等扫描版多栏/表格样本再统一。
- 视觉模型图像识别见 `TBD-image-recognition.md`：独立 change，动手前必须先回答该文件第 4 节的五项待定。
- 若后续要求审计报告引用原始文件的 `sha256`，按 `design.md` Open Questions 1 处理（让审计复用导入的 run），只改前端流程。
- 模板编辑页面与"另存为模板"仍是 TBD，不在任何 change 里；等导入主干稳定后单独提。