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
- **文档模板与视觉模型识别：本 change 明确不做。** 模板编辑页面与本轮功能无关；provider 化的图像识别见同目录 `TBD-image-recognition.md`。

**不做**：模板编辑页面与"另存为模板"、正文骨架/占位符/预填字段表、富文本、导出、批量多文件合并成一份文档、用视觉模型替代本地 OCR、把模型接进 `extract`（provider 是另一条切片）、异步任务队列与进度推送（POC 同步执行，前端显示阶段报告）。

## Capabilities

### New Capabilities

- `document-import`: 把客户上传的原始材料变成编辑器里的文本——支持 PDF（文本层与扫描件）、DOCX、PNG/JPG；逐文件报告解析结果与失败原因；OCR 来源的内容在数据里可识别，不得冒充已确认；解析结果通过信封提供给前端，导入的不可靠性止于冻结快照之前。

### Modified Capabilities

（无。`document-editor` 是 `editor-shell` 这个未归档 change 的 delta，本 change 不改它的要求；两者的衔接见 `design.md`，归档顺序为先 `editor-shell` 再本 change。）

## Impact

- **代码**：`app/parsing/parse.py`（DOCX + OCR 分支、失败原因）、`app/state.py`（`ParsedDoc.form` 两个字面量，冻结文件需签字）、`app/api/envelope.py`（`documents`）、`app/nodes/parse.py`（聚合"部分成功/全失败"时的可读原因，已有 `partial`/`failed` 逻辑，仅需覆盖新错误码）、`web/src/api/client.ts`（multipart 上传）、`web/src/components/DocumentActions.tsx`（真按钮）、`web/src/App.tsx` / `EditorColumn.tsx`（填入文本 + 逐文件结果）、`web/src/api/types.ts`（`documents` 类型）
- **系统依赖**：`tesseract` + 语言包（macOS：`brew install tesseract tesseract-lang`）；缺失时功能降级为明确报错，CI 不装也能跑（测试用 stub/跳过）
- **测试**：DOCX 解析（构造最小 docx）、OCR 分支（引擎缺失 → 明确错误；注入假 OCR 结果 → 文本与 bbox）、失败语义、信封字段、前端上传流程与错误展示；既有 330+109 个测试必须保持全绿（导入不改变任何既有路径的行为）
- **风险**：OCR 认错金额/公司名而被静默采用（→ 用 `inferred` + `image_ocr` 标注 + 面板提示"待核实"，且不覆盖已确认字段）；大文件/多页 OCR 拖慢同步请求（→ 页数/大小上限 + 一次一文件）；把 docx 标成 `pdf_text` 之类的"凑合"（→ 明确加字面量，禁止复用）；上传内容被执行（→ 只做文本抽取，绝不解析宏/嵌入对象）