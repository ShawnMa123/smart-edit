# Demo record — file import (`document-import`)

Evidence for tasks 6.1–6.3. Artifacts are zh per `openspec/config.yaml`; commands and outputs are verbatim.

## 环境

| 项 | 值 |
|---|---|
| 后端 | `SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json .venv/bin/uvicorn app.api.main:app --port 8010` |
| 前端 | `npm --prefix web run dev`（浏览器路径经 `/api` 代理到 8000） |
| pymupdf | 1.28.2（已装，`Page.get_textpage_ocr` 可用） |
| tesseract | **本机未安装**（brew 有 5.5.4）→ 图片走"明确拒绝"分支；装上即走识别分支，代码不变 |
| 新增 Python 依赖 | **0**（DOCX 用标准库 zip+XML；OCR 由 pymupdf 驱动系统 tesseract） |

## 命令

```bash
# 1) 解析层单测（DOCX / OCR / 失败语义 / 上限）
.venv/bin/python -m pytest tests/test_parse_import.py -q          # 16 passed

# 2) 真实 HTTP 端到端（需要先起 8010 的后端）
VITE_E2E=1 VITE_E2E_IMPORT=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.import.test.ts             # 4 passed

# 3) 回归
.venv/bin/python -m pytest -q                                     # 347 passed
npm --prefix web run test                                         # 125 passed / 9 skipped (http e2e)
npm --prefix web run typecheck                                    # clean
```

## 6.1 实测输出（真实 HTTP，`fixtures/imports/`）

| 输入 | `form` | 阶段 | 结果 |
|---|---|---|---|
| `guarantee.docx`（2 段 + 1 张 2×2 表格 + 一个宏部件） | `docx_text` | `parse:done` | 149 字符，含 `DEMAND GUARANTEE` / `Adidas AG` / `USD 500,000.00`；宏部件被忽略、未执行 |
| `scan.png`（1×1 图） | `image_ocr` | `parse:failed` | `ocr_engine_missing: local OCR engine unavailable (install tesseract plus its language data)`，`full_text=""` |
| `notes.txt` | `plain_text` | `parse:done` | 与改造前完全一致（走文本路径，未触碰 OCR） |
| `sheet.xlsx` | — | `parse:failed` | `unsupported_mime: …spreadsheetml.sheet is outside the POC's supported range` |

装上 tesseract 后，同样的 `scan.png` 会走识别分支：`form` 仍是 `image_ocr`，`errors` 为空且 `full_text` 非空——
测试同时断言这两条分支（`test_image_ocr_keeps_the_block_geometry` 用 stub，`test_missing_ocr_engine_is_reported_not_crashed` 用真实缺失）。

## 6.2 回归

- 粘贴文本 → `normalize` → `audit` 的路径未改动：`tests/test_api.py`、`tests/test_runtime.py`、
  `tests/test_audit_acceptance.py` 全绿（347 passed）。
- **一处既有断言按新契约更新**：`tests/test_parse.py::test_scan_like_pdf_raises_not_silent` 过去断言
  "无文本层 → `no_text_layer`"；现在扫描件改走 OCR，该测试改为断言"**没有文本就必须是错误**，
  且错误码是 `ocr_engine_missing` / `no_text_recognized` / `ocr_failed` 之一"——被替换的是死路，
  不是那条保证。
- 信封新增 `documents` 一个键；既有 10 个键与 `INCOMPLETE_RESULT` 语义不变（`test_envelope_carries_every_required_key`）。

## 6.3 这个构建对导入做了什么 / 没做什么

**做了**

- PDF 文本层（`pdf_text`，带页号与区域）、扫描版 PDF（逐页 OCR）、DOCX（标准库，含表格文字，不执行宏/嵌入对象）、
  PNG/JPEG（OCR，区域坐标指向图片）。
- 逐文件失败码：`unsupported_mime` / `ocr_engine_missing` / `no_text_recognized` / `image_open_failed` /
  `pdf_open_failed` / `docx_unreadable` / `file_too_large` / `too_many_pages` / `read_failed` / `file_not_found`。
- 信封 `documents[]`（不含 `blocks`，避免响应体膨胀），前端"Import file"真按钮、逐文件结果清单、
  「重新上传 / 从空白开始」、多个成功由用户选一个、覆盖用户已输入内容前先确认。
- 上限：20 MB / 30 页 OCR（常量在 `app/parsing/parse.py`）。

**没做（以及为什么）**

- **视觉模型图像识别**：见同目录 `TBD-image-recognition.md`（没有 bbox 会让证据自证、没有坐标就没有
  "待核实"落点、可复现性）。触发条件与待定项都在那个文件里。
- **置信度分数**：pymupdf 不暴露逐词 conf；用"OCR 文本 → 字段按 `inferred` 落库 → 未确认必为
  `needs_input`"表达可靠性，而不是给一个不可信的百分比。
- **模板编辑页面 / 另存为模板**：与本轮无关，TBD。
- **多文件合并成一份文档**：spec 明确"一次一个文档进编辑器"。
- **文本框 / 页眉页脚文字**：只承诺正文段落与表格。
- **异步任务与进度推送**：POC 同步执行，`StageReport` 表达完成/失败。
- **`.doc`（旧版二进制 Word）**：明确拒绝，不"尽力解析"。

## 已知边界

1. 导入的 run 与随后审计的 run 是两个 run（`design.md` Open Questions 1）；审计报告里没有原始文件的 `sha256`。
2. 本机未装 tesseract，图片路径的**成功**分支只在单测（stub）中验证过；真实引擎下的中文识别质量未实测，
   这也是 `TBD-image-recognition.md` 触发条件里那条"错识率实测"的来源。
3. OCR 语言默认 `chi_sim+eng`（猜测值），可用 `SMART_EDIT_OCR_LANGS` 覆盖。