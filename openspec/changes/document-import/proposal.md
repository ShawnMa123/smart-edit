# Proposal

## Why

现在客户只能在编辑器里**手打或粘贴**文本：中间栏是一块 textarea（`web/src/components/EditorColumn.tsx`），`Import file · not implemented` 是标签化的占位（`web/src/components/DocumentActions.tsx`）。而客户手上的原始材料是 PDF 保函、Word 草稿、扫描件照片——要他们先抄一遍才能审，等于把这个产品最有价值的一步（从原始材料开始）掐掉了。

后台其实**已经有一半**：`POST /runs` 接受 multipart 上传并落盘 + `sha256`（`app/api/main.py`、`app/runs.py`），`parse` 能读 PDF 文本层并给出 `page`/`bbox`（`app/parsing/parse.py`）。真正缺的三件事：**DOCX 与图片根本不认**（`_form_for` 只认 pdf/eml/txt；扫描件直接报 `no_text_layer ... OCR required`）、**解析出来的全文到不了前端**（`to_envelope()` 里没有 `docs`）、**前端没有上传入口**。

现在做正合适：`agent-audit` 的引擎、闸门、模板能力都已落地（54/55，330 个测试），审计已经不缺"判定"，缺的是"被审的文本从哪来"。而导入的不可靠性（OCR 会认错字）必须停在**冻结快照之前**，这正好是现有架构已经划好的线。

## What Changes

- **DOCX 支持（零新依赖）**：docx 就是 zip + `word/document.xml`，用标准库 `zipfile` + `xml.etree` 抽段落与表格文字；不安装 python-docx、**不打开 Word、不执行宏或嵌入脚本**（ED-03）。
- **图片与扫描件走本地 OCR**：用已装好的 pymupdf（1.28.2，`Page.get_textpage_ocr` 存在）+ 系统 tesseract（5.5.4，本机未装，需 `brew install tesseract tesseract-lang`）。图片可直接当文档打开，因此 PNG/JPG 与扫描版 PDF 共用一条路径，`blocks` 带图片坐标 `bbox`（ED-03/04）。**不新增 Python 依赖。**
- **明确的失败语义**：tesseract 缺失 → `ocr_engine_missing`；打不开 → `image_open_failed`；识别为空 → `no_text_recognized`；每文件独立记录在 `ParsedDoc.errors`，**绝不返回空 `full_text` 冒充成功**（ED-05）。
- **前端上传入口**：`Import file` 从占位变成真按钮，选中文件 → `POST /runs` → `POST /runs/{tid}/stages/parse` → 把解析出的全文填进中间栏 textarea；逐文件显示解析结果与错误，失败时提供"重新上传 / 从空白继续"。
- **信封补 `documents`**：`{file_id, filename, form, errors, full_text}`（可选，纯增量），否则前端拿不到文本。
- **契约拓宽（需签字）**：`ParsedDoc.form` 是冻结字面量 `pdf_text | pdf_form | email | plain_text`，新增 `docx_text` 与 `image_ocr` 两个取值——现有取值不受影响，但这是冻结文件，按 `agent-audit` 0.2 的同一套流程记录批准。
- **OCR 来源的可信度用状态表达**：OCR 出来的字段一律 `inferred`（未人工确认），`app/audit/bind.py` 的 `unconfirmed → needs_input` 保证它**永远不可能**被当成"通过"；`full_text` 里也可能有错字，因此报告里该文件的 `form` 必须是 `image_ocr`，让人一眼看出证据等级（ED-04）。
- **PDF 版面保真（第二轮加入，2026-11-09）**：客户实测 `fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf`（25 页 / 715 块）后指出"导入的格式还是不像 PDF 原来的样式"。实测原因三条，全部是"信息拿到了但没用"：
  - 字号只有 `9 / 14 / 20 / 48` 四档，但我们用"≥1.3× 正文即标题、按倍率分三级"的规则，结果 20pt 的章节标题与 48pt 的封面**一起落成 H1**（25 页 25 个 H1），14pt 反而落到 H3；
  - PDF 里**粗体/斜体信息在字体名与 span 标志位里**，我们没读，强调全部丢失；
  - 页码（24 个纯数字块）、每页版权页脚、以及页边界，全被当成普通正文段落，读者看不出"这是第几页、这页在哪结束"。
  两处我们**做对了但不彻底**的：`page` 与 `bbox` 已经存在于每个块上（PDF 侧一直有），只是没有进入富文档。
- **PDF 保真的具体做法**：① 按**字号排名**定层级（最大 → H1、次之 → H2、再 → H3，正文不入级），而不是固定倍率；② 从字体名与 span 标志位读**粗体/斜体**写成 marks；③ 每个块带**显示用属性**（`fontSize` / `fontFamily`），编辑器按原字号渲染；④ 块保留 `page`，并在页边界插入**不产生文本**的 `pageBreak` 节点，让读者看见"第 N 页到此为止"；⑤ **不删除任何内容**——页码与页脚作为独立块保留（它们是原文件的一部分），只是不再与正文粘连。
- **与审计的边界不变**：以上属性与 `pageBreak` 都**不进入**投影文本（`richToPlainText` 只投影文字与结构标记），所以"保真"不会改变审计读到的字符；`full_text` 逐字不变。
- **PDF 视觉行（第三轮加入，2026-11-09）**：Contents 页的页码被渲染到标题的下一行。实测根因不是目录特例：`get_text("dict")` 的 `line` 并不等于视觉行，25 页样本有 **138 / 717** 个 block 的 line 共享同一水平带（目录 19 行、正文填空 119 行）；当前实现按 line 补 `\n`，编辑器又用 `pre-wrap` 把它渲染成真实换行。做法：**同一 block 内**按垂直重叠归并为视觉行，行内片段按 x 用一个空格连接、行间保留换行；解析层与富文本层共用同一实现，`full_text` 与投影继续逐字相等；不可见控制字符（`\x07` / `\x08`）移除、`\t` 变空格，可见空白（`\xa0`、全角空格）保留。实测 `full_text` **50799 → 50022** 字符、换行 **915 → 735**，块数仍 **715**、页边界仍 **24**。
- **第三轮不做**：跨 block 的表格行聚类（第一轮的 ` | ` 行为）、页码右对齐与填空保宽（显示层）、目录专用两列表格、OCR 路径的行重组。
- **PDF 布局保真（第四轮加入，2026-11-09）**：客户指出 `Beneficiary:` 后面的长下划线"没识别出来"，目录/页码的格式仍对不上。根因是 PDF 有两层内容：`get_text()` 只读**文字**，而空白下划线是**矢量绘制**（`page.get_drawings()` 里的 0.3pt 描边线）；"靠右"也只存在于坐标里，不在文字中。实测这份样本有 **226 条水平绘制线**、**171 个文本行**能关联到空白下划线（另有 24 个页眉分隔线被排除）、**116 个大间距**被线覆盖、**26 个单片段靠右**（24 个页码 + `Page` + 一个占位符）、**25 个单行大间距**（其中 19 个是目录行），而**含布局的多行 block 为 0**。做法：读取 `get_drawings()`，只对**单视觉行** block 加 `row=true` 与**显示用内联 gap 节点**（`rule=true` 渲染为下划线；`rule=false` 作为不可见弹性间距，按 PDF 宽度分配 flex-grow）；单片段且贴着右边界（页码、`Page`）加 `align=right`。所有 gap/align 都是显示属性，**不产生任何字符**：`full_text` 仍 **50022** 字符、**715** 块、**24** 个页边界，审计结论不变。
- **第四轮不做**：把空白做成可填写的表单字段（A+；第五轮只落地"可填写空白"）、绝对定位/像素级重排、跨 block 的表格行、OCR 路径的绘制线提取。
- **可填写空白与光标稳定（第五轮加入，2026-11-09）**：用户在导入后的下划线处输入时，光标会跳到文档最后一行，且无法把光标放进下划线。两个独立原因：① `useRichEditor` 在每次 `onUpdate` 后用**新对象**回调 `onChange`，但没有更新 `applied` ref；父组件把同一个结果作为 `document` 传回时，effect 把它当成外部文档并 `setContent`，选区被重置到文末；② `pdfGap` 是 `atom: true` 且没有 `content`，里面没有文字位置。做法：修 `applied` 回声守卫（只有外部导入/恢复才 `setContent`）；把 `pdfGap` 改为**可编辑的内联容器**（`content: text*`）：空空白仍是纯装饰、不产生字符；用户键入的文字显示在下划线上，并**进入投影文本与审计输入**；相邻文字与空白之间按需补一个空格。`full_text` 仍由解析层产生（50022 字符），块数/键/页边界不变；只有用户实际填入内容时，投影才增加那些字。
- **第五轮不做**：真正的 `<input>` 字段与结构化字段抽取（把空白映射为 key/value 的表单模型）、绝对定位/像素级重排、跨 block 表格、OCR 绘制线。
- **不做**：模板编辑页面与"另存为模板"、正文骨架/占位符/预填字段表、导出、批量多文件合并成一份文档、用视觉模型替代本地 OCR、把模型接进 `extract`（provider 是另一条切片）、异步任务队列与进度推送（POC 同步执行，前端显示阶段报告）。**富文本编辑**已由 `rich-text-editor` 交付，本 change 只负责"导入怎么把版面交出去"。

## Capabilities

### New Capabilities

- `document-import`: 把客户上传的原始材料变成编辑器里的文本——支持 PDF（文本层与扫描件）、DOCX、PNG/JPG；逐文件报告解析结果与失败原因；OCR 来源的内容在数据里可识别，不得冒充已确认；解析结果通过信封提供给前端，导入的不可靠性止于冻结快照之前。

### Modified Capabilities

（无。`document-editor` 是 `editor-shell` 这个未归档 change 的 delta，本 change 不改它的要求；两者的衔接见 `design.md`，归档顺序为先 `editor-shell` 再本 change。）

## Impact

- **代码**：`app/parsing/parse.py`（DOCX + OCR 分支、失败原因）、`app/state.py`（`ParsedDoc.form` 两个字面量，冻结文件需签字）、`app/api/envelope.py`（`documents`）、`app/nodes/parse.py`（聚合"部分成功/全失败"时的可读原因，已有 `partial`/`failed` 逻辑，仅需覆盖新错误码）、`web/src/api/client.ts`（multipart 上传）、`web/src/components/DocumentActions.tsx`（真按钮）、`web/src/App.tsx` / `EditorColumn.tsx`（填入文本 + 逐文件结果）、`web/src/api/types.ts`（`documents` 类型）
- **第三轮代码与测试**：`app/parsing/pdf_layout.py`（新增共享视觉行层）、`app/parsing/parse.py`（PDF 文本层改 `get_text("dict")` + 共享层）、`app/parsing/rich_pdf.py`（text nodes 改用视觉行）；`tests/test_rich_pdf_fidelity.py` / `tests/test_import_acceptance.py` 更新为 50022 字符、735 换行，并断言目录行、填空句与控制字符；`tests/test_rich_honesty.py` 断言审计判定不变。
- **系统依赖**：`tesseract` + 语言包（macOS：`brew install tesseract tesseract-lang`）；缺失时功能降级为明确报错，CI 不装也能跑（测试用 stub/跳过）
- **测试**：DOCX 解析（构造最小 docx）、OCR 分支（引擎缺失 → 明确错误；注入假 OCR 结果 → 文本与 bbox）、失败语义、信封字段、前端上传流程与错误展示；既有 330+109 个测试必须保持全绿（导入不改变任何既有路径的行为）
- **风险**：OCR 认错金额/公司名而被静默采用（→ 用 `inferred` + `image_ocr` 标注 + 面板提示"待核实"，且不覆盖已确认字段）；大文件/多页 OCR 拖慢同步请求（→ 页数/大小上限 + 一次一文件）；把 docx 标成 `pdf_text` 之类的"凑合"（→ 明确加字面量，禁止复用）；上传内容被执行（→ 只做文本抽取，绝不解析宏/嵌入对象）