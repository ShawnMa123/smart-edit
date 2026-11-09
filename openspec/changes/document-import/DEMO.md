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
.venv/bin/python -m pytest -q                                     # 347 passed（第一轮当时；第二轮后为 378）
npm --prefix web run test                                         # 125 passed / 9 skipped（第一轮当时；第二轮后为 150 / 12）
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

## 第二轮：PDF 版面保真（2026-11-09）

客户实测 `fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf`（**25 页 / 715 块 / 50799 字符**）后指出"导入的格式还是不像 PDF 原来的样式"。

```bash
.venv/bin/python -m pytest tests/test_rich_pdf_fidelity.py -q   # 11 passed
.venv/bin/python -m pytest tests/test_import_acceptance.py -q   # 7 passed（真实样本）
npm --prefix web run test -- src/components/RichEditor.test.tsx # 13 passed（含属性与页边界）
VITE_E2E=1 VITE_E2E_RICH=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.rich.test.ts             # 3 passed
.venv/bin/python -m pytest -q                                   # 378 passed
npm --prefix web run test                                       # 150 passed / 12 skipped（HTTP e2e 需显式开关）
```

### 修前 / 修后（同一份 25 页样本，实测）

| 指标 | 第一轮 | 第二轮 | 说明 |
|---|---|---|---|
| 标题层级 | 25 个**全 H1** | **H1=1 / H2=23 / H3=1** | 按字号排名：48pt 封面 → H1、20pt 章节 → H2、14pt 副标题 → H3、9pt 正文不入级 |
| 粗体 | 0 | **75 处** | 从 span `flags` 与字体名取"或" |
| 页边界 | 0 | **24** | 25 页 → 24 个不产生文本的 `pageBreak` |
| 页码 / 页脚 | 混在正文里 | **保留**为独立块 | 客户要求"保留原样"，我们不删内容 |
| 富文档块数 | — | **739 = 715 + 24 页边界** | 解析块一个不少 |
| 投影 vs `full_text` | 有差异（分隔符） | **逐字相同** | `pageBreak` 与显示属性都不进投影 |
| 显示属性 | 无 | 每块带 `fontSize` / `fontFamily` / `page` | 编辑器按原字号渲染 |

`provenanceNote` 现在写成一句可读的话：

```
heuristic: 25 pages, levels from font-size rank, 25 headings, 24 page breaks, page numbers and footers kept
```

有 PDF 书签时改成 `levels from PDF bookmarks`（书签是该文件作者给的层级，优先于字号推断）。

### 判据与失败路径

- **只有一种字号** → 不产生任何标题（不猜）。
- **块内混排多种字号** → 整块按段落处理，绝不把"首行较大"的段落整段变成标题。
- **文字改动零容忍**：`test_import_acceptance.py` 断言投影逐字等于 `full_text`、块数相等。
- **审计不受影响**：`tests/test_rich_honesty.py` 用带 `pageBreak` + 字体属性的富文档再跑一遍，`counts` / `outcome` 与原样一致。
- **体积**：`npm --prefix web run build` 实测 **801.12 kB → 802.19 kB（+1.07 kB）**（HEAD 与本轮各构建一次，gzip 254.51 → 254.80 kB）；本轮只加了一个 `pageBreak` 节点与三个显示属性，**没有引入新包**（`@tiptap/core` 只是从传递依赖提为显式依赖），并移除了与 StarterKit 重复注册的 `underline`（测试日志里那条 duplicate extension 警告随之消失）。

### 一处样本变动

`t1_contract.pdf` 已不在仓库根目录（只剩 `runs/` 下的上传副本，含个人姓名与证件号，**不应入库**），
因此把它从 HTTP e2e 中移除，改用已提交的 25 页样本作为 PDF 证据。

## 第三轮：PDF 视觉行（2026-11-09）

客户指出 Contents 页的页码被渲染到标题的**下一行**。根因不是目录特例：PyMuPDF 的 `line` 不等于视觉行，
同一 block 内会有多个 `line` 共享一个水平带——这份 25 页样本有 **138 / 717** 个 block 如此（目录 19 行、
正文填空 119 行）。编辑器又用 `white-space: pre-wrap` 把 `\n` 渲染成真实换行。

```bash
.venv/bin/python -m pytest tests/test_pdf_layout.py -q          # 11 passed（纯函数与两层一致性）
.venv/bin/python -m pytest tests/test_rich_pdf_fidelity.py -q   # 11 passed
.venv/bin/python -m pytest tests/test_import_acceptance.py -q   # 8 passed（真实 25 页样本）
.venv/bin/python -m pytest -q                                   # 390 passed
npm --prefix web run test                                       # 150 passed / 12 skipped
npm --prefix web run typecheck                                  # clean
npm --prefix web run build                                      # 802.19 kB（gzip 254.80 kB）
VITE_E2E=1 VITE_E2E_RICH=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.rich.test.ts             # 3 passed（739 块 / 24 页边界）
```

### 修前 / 修后（同一份 25 页样本，实测）

| 指标 | 第二轮 | 第三轮 |
|---|---|---|
| 文本块数 | 715 | **715**（不跨 block 合并） |
| `full_text` 字符 | 50799 | **50022** |
| 换行 | 915 | **735** |
| `pageBreak` | 24 | **24** |
| 目录行 | `Tender Guarantee Standard` + 下一行 `4` | **`Tender Guarantee Standard 4`** |
| 正文填空句 | `We are informed by` + 下一行 `(the “Tenderer”)…` | **一行** |
| 不可见控制字符 | `\x08`×21 / `\x07`×5 / `\t`×25 | **0 / 0 / 0**（`\t` → 空格） |
| 标题 / 粗体 | H1=1 / H2=23 / H3=1，粗体 75 | **不变** |
| 投影 vs `full_text` | 逐字相同 | **逐字相同** |

### 规则与口径

- **只在 block 内重组**：同一水平带的 `line`（垂直交集 > 较矮者高度的 50%）归为一行；行内按 x、用一个空格连接；行间保留 `\n`。
- **解析层与富文本层共用** `app/parsing/pdf_layout.py`：`parse.py` 改用 `get_text("dict")`，`rich_pdf.py` 用同一 `visual_rows`。两种 `get_text` 模式在这份样本的 **715 / 715** 个 block 上文本一致，切换没有字符漂移。
- **可见字符仍然逐字相同**：`\xa0` 与全角空格保留（有断言）；只移除不可见的 `\x07` / `\x08` 并把 `\t` 变空格。
- **只保证"同行"**：页码不右对齐、填空宽度会塌成一个空格——这是显示层方案 B，独立 change；跨 block 的表格行与 OCR 路径的行重组也不在本轮。

## 已知边界

1. 导入的 run 与随后审计的 run 是两个 run（`design.md` Open Questions 1）；审计报告里没有原始文件的 `sha256`。
2. 本机未装 tesseract，图片路径的**成功**分支只在单测（stub）中验证过；真实引擎下的中文识别质量未实测，
   这也是 `TBD-image-recognition.md` 触发条件里那条"错识率实测"的来源。
3. OCR 语言默认 `chi_sim+eng`（猜测值），可用 `SMART_EDIT_OCR_LANGS` 覆盖。