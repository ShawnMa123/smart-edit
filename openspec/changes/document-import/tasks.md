# Tasks

> 依据：`proposal.md`（范围）、`specs/document-import/spec.md`（要求）、`design.md`（做法 D1–D10）、
> `TBD-image-recognition.md`（明确暂缓的视觉模型路线）。
> 每组自带该组的测试与文档；第 6 组只做跨组集成与验收。

## 0. 契约与签字（最先做，且只做加法）

- [x] 0.1 `app/state.py`：`ParsedDoc.form` 增加两个取值 `docx_text`、`image_ocr`（保留现有四个）。Verify: `git diff` 只改这一行；所有既有测试全绿；改动记录写进本文件（与 `agent-audit` 0.2 同一套签字流程）。

  **改动记录（2026-11-09）**：`ParsedDoc.form` 的字面量由 4 个取值扩到 6 个，**没有**改动任何字段、类型或既有取值；
  这是一个"拓宽枚举"的加法，现有代码与数据完全不受影响。A 在采纳本 change 时批准；B / C 追认待签——
  他们若反对，回滚方式是把字面量改回 4 个取值并删除 DOCX/OCR 两个分支（`app/parsing/parse.py`），
  不影响其他任何模块。证据：`tests/test_parse_import.py`、`tests/test_api.py::test_the_envelope_carries_the_imported_documents`。
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

## Workflow follow-up

- `ParsedDoc.form` 的两个新取值需要在归档前记录批准（与 `agent-audit` 0.2 同一张签字表）；未签字前不得把本 change 归档。
- `editor-shell` 的 `document-editor` delta 把 "file import" 列为"present but marked not implemented"；本 change 落地后需要在那份 delta 里同步（改它自己 change 的规格，不是本 change 的）。
- 视觉模型图像识别见 `TBD-image-recognition.md`：独立 change，动手前必须先回答该文件第 4 节的五项待定。
- 若后续要求审计报告引用原始文件的 `sha256`，按 `design.md` Open Questions 1 处理（让审计复用导入的 run），只改前端流程。
- 模板编辑页面与"另存为模板"仍是 TBD，不在任何 change 里；等导入主干稳定后单独提。