# Design

## Context

动机见 `proposal.md`。做决策前必须知道的现状（均已核对代码与这台机器）：

| 事实 | 对本设计的影响 |
|---|---|
| `POST /runs` 已接受 multipart（`app/api/main.py`），落盘 + `sha256`（`app/runs.py::store_upload`） | 上传不需要新端点；缺的是"选中文件"的前端入口 |
| `parse_file()` 逐文件返回 `ParsedDoc{form, blocks, full_text, errors}`，**从不抛异常**（`app/parsing/parse.py`） | DOCX/OCR 只要加 dispatch 分支，聚合逻辑（`partial`/`failed`）已存在 |
| `_form_for()` 只认 pdf / eml / txt；不认识的直接 `unsupported_mime` | 加 `.docx`、`image/png`、`image/jpeg` 三处匹配 |
| `ParsedDoc.form` 是**冻结** `Literal["pdf_text","pdf_form","email","plain_text"]`（`app/state.py`） | 新增 `docx_text` / `image_ocr` 需签字；不能复用旧值 |
| `to_envelope()` 没有 `docs` | 前端拿不到 `full_text`，必须加 `documents` |
| `bind.py`：`inferred → unconfirmed → needs_input` | OCR 值天然落在"未确认"，不需要新机制 |
| `pyproject.toml` 无 docx / OCR / 图像库 | DOCX 用标准库；OCR 用 pymupdf + 系统 tesseract |
| pymupdf **1.28.2 已装**，`Page.get_textpage_ocr` 存在；`fitz.open()` 可直接打开图片 | 图片与扫描件共用一条路径，**零新 Python 依赖** |
| 本机 **tesseract 未安装**（brew 有 5.5.4 可用）；Pillow / pytesseract 未装 | 依赖是**系统级**的；缺失必须表现为明确错误而非崩溃 |
| `app/llm.py` 只有 `fixture:` 可用，`openai:` 抛 `NotImplementedError` | 本 change 不依赖模型；OCR 走本地，抽字段维持现状 |

## Goals / Non-Goals

**Goals:**

- 一条可用的主干：选文件 → 上传 → 解析 → 文本进编辑器，失败逐个可见。
- 四种输入（PDF 文本层 / PDF 扫描件 / DOCX / 图片）在数据上**来源可识别**。
- 零新增 Python 依赖；缺系统 OCR 引擎时优雅降级为明确错误。
- 导入的不确定性止于快照之前：OCR 文本可以进入编辑器，但**不可能**被当成已确认值通过审计。
- 既有行为零回归：不传文件（纯文本）的路径与今天完全一致。

**Non-Goals**（proposal 已列，这里只补设计层边界）：模板编辑页面与"另存为模板"；正文骨架/占位符/预填字段表；批量多文件合并成一份文档；异步任务与进度推送；视觉模型 OCR（见 `TBD-image-recognition.md`）；把 provider 接进 `extract`。

## Decisions

### D1. 复用现有上传与 parse 链路，不新建导入服务

```
POST /runs (multipart, 已有)  -->  files[] + sha256
POST /runs/{tid}/stages/parse -->  ParsedDoc[]（新增 docx/ocr 分支）
GET  /runs/{tid}              -->  documents[]（新增键）
```

*为什么不新建 `POST /imports`：* 上传、落盘、`sha256`、逐文件错误、`StageReport` 全部已存在且有测试；新端点意味着第二套错误语义与第二套存储。**替代方案**：`POST /imports` 返回"草稿文档"——被否决，因为编辑器当前就是"文本 + 字段表"，没有草稿文档对象（见 D2）。

### D2. 导入的产出是"文本"，不是"草稿文档"

中间栏是 textarea，它的内容就是被审计的源文本。所以导入的终点是 `full_text` 进入 textarea，**不引入 `draft_body`**。

*为什么不做草稿对象：* 那会同时引入"已确认字段不被覆盖"、"草稿与快照的区别"、"骨架"三个新概念，而这一轮用户要的是"别再手打"。*代价：* 导入的 run 与随后的审计 run 是两个 run（审计仍由 `createRun(文本)` 新建），原始文件的 `sha256` 不在审计报告里。这个取舍写进 Open Questions 1。

### D3. `form` 扩两个取值，并以此承载"证据等级"

`ParsedDoc.form` 增加 `docx_text`、`image_ocr`。它是**唯一**让人一眼看出"这段文字是读出来的还是认出来的"的字段，也是报告与 UI 的展示依据。

*为什么不动 `blocks` 结构：* `ParsedBlock{page, bbox, text, kind}` 对 OCR 完全够用（图片就是 1 页，`bbox` 是图片坐标）。*为什么必须新值而不是复用：* 把 docx 标成 `pdf_text` 会让 `provenance` 检查与用户都误判证据来源——这正是"契约里说谎"。

### D4. DOCX：标准库解析，范围明确收窄

`zipfile.ZipFile(path)` → 读 `word/document.xml` → 用 `xml.etree.ElementTree.iter()` 按文档顺序取 `w:p`（段落）与 `w:tbl`/`w:tc`（表格单元）里的 `w:t` 文本。

- 只处理 `.docx`（OOXML zip），**不支持**旧版二进制 `.doc`（明确报 `unsupported_mime`）。
- 每个段落一个 `ParsedBlock(kind="paragraph")`，表格单元一个 `ParsedBlock(kind="table_cell")`，`page`/`bbox` 为 `None`。
- **不**解析样式、不还原粗体/斜体（ED-02 是编辑器的事，不是导入的事）；**不**读 `vbaProject.bin`、不解析外链、不实例化任何嵌入对象。
- 损坏 / 缺 `word/document.xml` → `errors=["docx_unreadable: ..."]`。

*替代方案：* `python-docx`（多一个依赖，收益只是样式）；`pandoc` / `libreoffice` 子进程（重，且引入"执行未知文档"的风险面）。标准库方案在"抽文字"这个目标上足够，安全面最小。

### D5. OCR：pymupdf 驱动 tesseract，图片与扫描件同一条路

```python
doc = pymupdf.open(path)                                  # PNG/JPG 也能开，成为 1 页文档
textpage = page.get_textpage_ocr(language=LANGS, dpi=OCR_DPI)
blocks = page.get_text("blocks", textpage=textpage)       # bbox 落在源页/图片坐标
```

- `LANGS` 默认 `chi_sim+eng`，可用 `SMART_EDIT_OCR_LANGS` 覆盖；`OCR_DPI` 默认 300。
- **扫描版 PDF** 也走这里：先看文本层是否为空，空则逐页 OCR —— 顺手解掉今天 `no_text_layer` 的死路。
- 引擎缺失的判定：OCR 调用抛错且错误文本指向 tesseract / tessdata → `errors=["ocr_engine_missing: ..."]`；不做导入期的 `which tesseract` 隐式探测（不同部署下会误判），以实际调用结果为准。
- **置信度**：pymupdf 不暴露逐词 conf。因此用 D6 的"状态"表达可靠性，而不是伪精确的数字。

*替代方案：* `pytesseract` + Pillow（能拿到逐词 conf，但多两个依赖且要自己做图像对象转换）；视觉模型（见 TBD 备忘录：没有 bbox 会让证据自证）。

> **第二轮修正（D11–D16）**：本节的文字块结构规则（字号、层级、marks、页边界、页码处置）已被 D11–D16
> 取代——D5 只保留"用 pymupdf 读文本块与坐标"这一条。原规则"≥1.3× 正文即标题、按倍率分三级"被实测
> 证伪（一份 25 页 PDF 产出 25 个 H1），且原方案"删除页脚与页码"违背客户"保留原样"的要求。

### D6. OCR 值的可信度用 `inferred` 表达，不用分数

OCR 文本进入 `docs[].full_text` 之后，`extract` 抽出的候选值仍按现有规则落地：定位到 span 的为 `extracted`，OCR 文本里匹配不上的落 `inferred`。而**无论哪种**，OCR 来源的文档在 UI 与报告里都带 `form="image_ocr"`，提示"这是识别出来的"。

关键不变量（已有测试守着）：`inferred` 且未确认 → `unconfirmed` → 依赖它的检查是 `needs_input`，**不是** `pass`。所以"OCR 认错一个金额并被静默采用"在数据上被堵住：它最多变成"需要人确认"。

*为什么不做置信度阈值：* 没有可靠的逐词 conf 时，阈值只是把不确定性藏进一个数字。宁可整类标"待核实"。

### D7. 信封加 `documents`，并且只加这一个键

```json
"documents": [{"file_id": "F-…", "filename": "scan.png", "form": "image_ocr",
               "errors": [], "full_text": "…"}]
```

- 纯增量：现有 10 个键不变，`IncompleteResult` 语义不变（`stages` 缺失仍然 500）。
- **不**在这次把 `blocks` 也给前端：本轮 UI 只需要全文；`blocks` 会显著放大响应体，留给"回到原文高亮出处"的后续需求。
- 未解析时 `documents` 为空列表（不是 `null`）："还没解析"与"解析出零个文档"在 UI 上是同一句话。

### D8. 失败语义具体到码，前端逐条展示

| 情形 | `errors` 里的码 | 阶段报告 | 用户可做的 |
|---|---|---|---|
| 类型不支持 | `unsupported_mime` | `partial`（若还有其他文件） | 换个文件 |
| 引擎缺失 | `ocr_engine_missing` | `partial` / `failed` | 按提示装引擎；或从空白继续 |
| 识别为空 | `no_text_recognized` | `partial` / `failed` | 重传更清晰的图；或手输 |
| 打不开 | `image_open_failed` / `pdf_open_failed` / `docx_unreadable` | 同上 | 重传 |
| 超限 | `file_too_large` / `too_many_pages` | 同上 | 拆分 / 压缩 |

*为什么复用 `errors` 而不是新字段：* `ParsedDoc.errors` + `StageReport(status, reason)` 已经是"没读到"的标准表达，加字段等于两套真相。

### D9. 规模上限作为配置，不作为隐藏逻辑

`MAX_BYTES`（默认 20 MB）与 `MAX_OCR_PAGES`（默认 30 页）放在配置常量里，超限在 `parse_file` 内以 `errors` 报出。OCR 是同步且慢的（300 dpi 每页百毫秒级），上限是为了不让一次请求把服务挂住。

*替代方案：* 异步任务 + 进度推送 —— POC 没有队列，且 `StageReport` 已经能表达"做完了 / 失败了"。

### D10. 前端：一个按钮 + 一份结果清单，不做上传队列

```
[Import file]   (隐藏 <input type=file accept=".pdf,.docx,.png,.jpg,.jpeg">)
   --> createRunWithFiles(files)        新增 client 函数（FormData，multipart）
   --> triggerStage(tid, 'parse')
   --> 取 documents[]：
         唯一成功 --> 填入 textarea；顶部横幅："文本识别自 scan.png（image_ocr），请核对"
         多个成功 --> 列出，让用户选一个填入
         有失败   --> 逐条列出原因 + "重新上传 / 从空白继续"
```

- 导入**不自动触发** `extract` / `audit`：用户先在编辑器里改，再点 `Run spec audit`（现有流程不变）。
- `Import file · not implemented` 这个标签与 `UNAVAILABLE_ACTIONS` 里的对应条目要一起删掉，否则 UI 自相矛盾。

### D11. PDF 层级按字号**排名**，不按倍率

原规则（D5）：`size ≥ 1.3 × 正文基准` 即标题，再按倍率分 H1/H2/H3。实测这份 25 页保函只有 `9 / 14 / 20 / 48` 四档，倍率把 48pt 封面与 20pt 章节标题**一起**判成 H1（25 个 H1），14pt 的"Published July 2025"反而落到 H3。

新规则：把文档里出现过的字号去重、降序排名，`rank 0 → H1`、`rank 1 → H2`、`rank 2 → H3`，其余为正文；正文基准仍取**出现次数最多**的字号。结果：48 → H1、20 → H2、14 → H3、9 → 正文，层级顺序与视觉一致。

*为什么不用倍率阈值：* 阈值对"文档整体字号偏大"或"只有两档"的文档永远调不对。*替代方案：* 用 PDF 的**大纲书签**（`doc.get_toc()`）——这份文件没有书签，但**有书签时应当优先**（见 D12）。

### D12. 有书签就用书签，没书签才用字号

`pymupdf` 能读出 PDF 自带的大纲（`doc.get_toc()` → `[level, title, page]`）。书签是**文件作者给的**标题层级，比字号更可信。

规则：若书签非空，按书签的 `title` 与所在页匹配正文块 → 该书签决定其层级；匹配不上的块退回 D11 的字号排名。书签与字号冲突时**书签胜**，并在 `provenanceNote` 里写明"层级来自 PDF 书签"。

### D13. 粗体/斜体来自字体，写成 marks

每个 span 有 `flags`（bit 4 = 粗体，bit 1 = 斜体，PyMuPDF 的 `TEXT_FONT_BOLD`/`TEXT_FONT_ITALIC`）与 `font` 名（如 `Arial-BoldMT`、`Helvetica-Oblique`）。两者取"或"：标志位置位 **或** 字体名含 `Bold`/`Black`/`Heavy` → `bold`；含 `Italic`/`Oblique` → `italic`。

*为什么两者都要：* 有些 PDF 只设字体名不设标志位，反之亦然；取"或"不会把普通文字误判成粗体（宁可少判，不可错判）。MUST NOT 由字体**大小**推粗体。

### D14. 字号/字体作为**显示属性**，不进审计文本

每个块新增可选 `attrs: {fontSize, fontFamily, page}`：编辑器用内联样式渲染（`font-size: 9pt`），让"看起来像那份 PDF"；`richToPlainText` 完全忽略 attrs。

*代价：* 前端需要在 TipTap schema 里为 `paragraph`/`heading` 增加三个可选属性，并在 `RichDocument` 类型里声明；缺少属性时编辑器仍必须正常渲染（老数据兼容）。
*替代方案：* 只保留结构不保留字号——被否，因为客户要的正是"看起来像原样"。

### D15. 页边界用不产文本的 `pageBreak` 节点，页码/页脚**保留**

- 每个块带 `page`；相邻块 `page` 变化时插入 `{"type": "pageBreak"}`。它在编辑器里渲染成一条分隔线，**投影文本忽略它**（不增加任何字符）。
- 页码与页脚**不删除**：它们是原文件的一部分，且本 change 的口径是"尽量保留原样"。它们各自作为独立块存在（页码是纯数字块、页脚是它自己那一块），因此不会与正文粘连。
- `provenanceNote` 记录"共 N 页、M 处结构来自书签/字号、K 个页边界"。

*为什么与第一版方案相反：* 我最初建议"删掉页脚与页码"，客户明确要求**保留原样**；删内容比留内容更危险（少一行版权行没人发现，少一条条款也不会有人发现）。

### D16. 块数守恒与文字逐字不改

`rich` 的块数 MUST 等于解析块数（`pageBreak` 与空段落另计），每个块的文字与 `ParsedBlock.text` **逐字相同**（含 `\xa0` 与全角空格）。这条由测试守着：把 `rich` 投影回来，忽略 `pageBreak`，得到的字符序列必须与 `full_text` 一致（除块间隔符）。

*为什么这么严：* 一旦允许"顺手整理一下"，就再也说不清哪一行是原文、哪一行是我们润色过的。"保留原样"必须是可测的。

## Risks / Trade-offs

- **[OCR 认错关键值]** 用 `inferred` + `form=image_ocr` + "请核对"横幅，让错误止步于"待确认"；不引入不可信的置信分数。→ 命中 AC-05 的要求。
- **[tesseract 是系统依赖，CI 与同事机器可能没有]** 缺失时降级为明确错误，不是崩溃；测试用 stub 覆盖"引擎可用 / 不可用"两条分支，CI 不装也能全绿。
- **[OCR 慢，同步请求]** 页数 / 字节上限 + 一次一个文档进编辑器；超限明确拒绝，而不是让请求挂着。
- **[DOCX 变体多（模板、批注、文本框）]** 只承诺"抽到段落与表格文字"；抽不到的不承诺，且不因此失败（写进 Non-Goal）。
- **[两个 run 的取舍]** 导入 run 与审计 run 分离，审计报告里没有原始文件的 `sha256`。→ Open Questions 1，本轮明确接受。
- **[信封变大]** 一份 48k 字符的保函 → `documents` 多约 48 KB。→ 只给 `full_text`，不给 `blocks`；后续要用再谈分页读取。
- **[`ParsedDoc.form` 拓宽要签字]** 与 `agent-audit` 0.2 同一套流程；这次是"加两个取值"，不动既有取值与字段。

## Migration Plan

1. **契约先行**：`ParsedDoc.form` 加两个取值（签字）+ 信封加 `documents`；此步不改解析行为，既有测试必须全绿。
2. **DOCX**：`_form_for` 认识 `.docx` + 标准库解析 + 失败码；单测覆盖"正常 / 损坏 / 含宏"。
3. **OCR**：`_form_for` 认识图片 + 扫描版 PDF 回退；单测用 stub 覆盖"引擎可用 / 缺失 / 空结果"（CI 不装 tesseract 也能过）。
4. **前端**：上传按钮 + 结果清单 + 填入 textarea；组件测试覆盖"成功 / 多文件 / 部分失败"。
5. **回滚**：删掉两个新 `form` 取值、`documents` 键、DOCX/OCR 分支即可回到今天的行为；无数据迁移（run 是进程内的）。

## Open Questions

1. **导入 run 与审计 run 是否合并** —— 本轮接受"两个 run"（审计仍由文本新建）。若后续要求审计报告能引用原始文件的 `sha256`，需要前端记住导入的 `thread_id` 并在同一 run 上跑 `normalize/audit`；只改 `web/src/App.tsx` 的流程，不改后端契约。
2. **多文件合并成一份文档** —— 现在 spec 明确"一次一个文档进编辑器"。若要"邮件 + 附件合成一份"，那是另一个能力（涉及合并语义与锚点），不在本轮。
3. **文本框 / 页眉页脚里的文字** —— DOCX 与 PDF 的"非正文"内容抽不抽，等有真实样本再定；本轮只承诺正文段落与表格。
4. **OCR 语言默认值** —— `chi_sim+eng` 是猜测；若客户材料以英文为主，质量与耗时都不同，等实测样本再调 `SMART_EDIT_OCR_LANGS`。