# Design: Agent 1 标准化

> **契约真相源**：`changes/poc-skeleton/design.md` + `specs/agent-contract/spec.md`。
> **实现落位**：`design/TradeAI_需求设计_v2/Implements_doc/Orchestrator_Agent_Layer_实施设计.md`（下称《编排层实施设计》）§6.2–§6.4。
> 本文只写 **Agent 1 的判定细节 + 与编排层的接缝**。
> 冲突消解顺序：契约 > 《编排层实施设计》§3–§6 > 本文。本文没写的判定 = 未定义，不得自行发挥。
> `parse` / `extract` / `normalize` 属于共享层 `app/parsing/`，**Agent 1 不是它们的私有者**。

## 0. 本版（v2）相对上一版改了什么

| # | 上一版 | 本版 | 为什么必须改 |
|---|---|---|---|
| 1 | `parse()` 返回 `{"docs":…, "parse_errors":…}` | 只返回 `list[ParsedDoc]`，错误进 `ParsedDoc.errors` | `EditState` 没有 `parse_errors` 键；契约冻结后加键要三人同意，且会在 `reset` 循环里叠加 |
| 2 | `extract()` 内部 `record(state, …)` | 纯函数返回 `ExtractResult(candidates, trail_entries, model_calls, failed_batches)` | 契约要求三函数"可在无图状态下单测"；`state` 根本不在作用域里（旧伪码跑不通） |
| 3 | 候选是扁平 `{key, raw_value, span, …}` | 候选带 `_source: Source`（`file_id/page/bbox/span/form_label`） | `FieldValue.source` 是 `Source` 结构，扁平 `span` 无法组装出处，跳原文会缺页码 |
| 4 | 只说"span 是最小片段" | 给出 **span 边界 5 条规则** + `MAX_SPAN_LEN=200` | `provenance_check` 的判据依赖它；含糊 = Agent 4 无法判定 |
| 5 | `normalize_ws` 只折叠空白 + 5 个全角标点 | **5 步权威规则**（NFKC / 零宽剔除 / 连字符 / 引号 / 空白） | 只折空白时 `900‑1234`（U+2011）、`“ABC”`、全角括号全部判为不可定位，`extracted` 会大面积假降级 |
| 6 | 三分类只有 `extracted/inferred` 会真正产生 | 补 **`missing` 占位**（`required` 字段缺候选时） | 否则 `missing` 永远是死枚举；B 与闸门只能看到"字段不存在"，无法区分"原文没写"与"没抽" |
| 7 | 截断要产 `N-` Finding，但没说 ID 怎么来 | 新增 `app/findings.py::materialize_findings()`，纯函数只出**无 id 的 Finding 草稿** | `Finding.id` 必须 agent 内自增且重跑不撞号；纯函数拿不到 `state`，不能自己编号 |
| 8 | 独立触发写"三个范围"，编排层只有 `normalize` 一个 target | 三档全部登记为 stage target（`parse` / `extract` / `normalize`） | 否则"只跑解析"在 API 上直接 `409 unknown_stage`，spec 的 Scenario 无法验收 |
| 9 | `business_type` 谁写不明（编排层表里写的是 `ingest`） | **唯一写入者 = `normalize`**，`ingest` 只透传 | `agent-contract`: "MUST 只由 Agent 1 写入"；两个写入方 = 出处不可查 |

> 第 9 条同时改了《编排层实施设计》§2.3 的写入者列，见该文件 §20.1 的裁决记录。

## 1. 落位：Agent 1 在工程里到底是什么

**Agent 1 不是一个 subgraph，而是三个阶段**：两个共享层纯函数（`extract` / `normalize`）＋一个共享层解析器（`parse`）＋三个薄节点。

| 层 | 文件 | 形态 | 说明 |
|---|---|---|---|
| 共享层 | `app/parsing/parse.py` | 纯函数 `parse_file(SourceFile) -> ParsedDoc` | 不抛异常，失败写 `errors` |
| 共享层 | `app/parsing/extract.py` | 纯函数 `extract(docs, field_keys, llm=…) -> ExtractResult` | 唯一模型入口 |
| 共享层 | `app/parsing/normalize.py` | 纯函数 `build_fields(...) -> NormalizeResult` + `normalize_ws` + `detect_business_type` | 无模型 |
| 节点 | `app/nodes/parse.py` / `extract.py` / `normalize.py` | 图节点（I/O、阶段记账、留痕写回） | 无业务判定 |
| 契约 | `app/state.py` | `FieldValue` / `Source` / `Finding` / `TrailEntry` / `StageReport` | D1 冻结 |
| 工具 | `app/findings.py` | `materialize_findings(state, drafts)` | `N-` / `B-` / `R-` 编号 + emit 留痕 |

**为什么不做成 subgraph 再 `wrap_agent("agent1", …)`**：
`parse → extract → normalize` 是主图的三个连续节点，任何 Agent（含 Agent 3 的 raw 模式）都要独立调用它们（契约"共享层"条）。
若包成 subgraph，独立触发就变成"图里套图"，`reuse docs`、`input_mode` 判定、`_candidates` 临时通道全部要跨图传递 —— 收益为零，复杂度翻倍。
`agent1` 在 `AGENT_SPECS` 里的意义只是**声明前置与产出**（`requires_keys=("files",)`、`produces=(docs, fields, extra_fields, business_type, findings)`），供 `require()` 与 `clear_previous_outputs()` 使用，不代表它有一个节点。

### 1.1 写哪些 state 键（与《编排层实施设计》§2.3 逐行一致）

| 键 | 写入阶段 | reducer | 备注 |
|---|---|---|---|
| `docs` | `parse` | 无（覆盖） | 复用时不写 |
| `_candidates` | `extract` 写 / `normalize` 清 | 无 | **临时通道，不进契约**；`normalize` 必须 `Overwrite([])` 清空 |
| `fields` | `normalize` | 无 | 只有 `fields.yaml` 内的键 |
| `extra_fields` | `normalize` | 无 | 字典外字段，**绝不混进 `fields`** |
| `business_type` | `normalize` | 无 | **唯一写入者**（`ingest` 仅透传） |
| `findings` | `normalize`（`N-`） | `operator.add` | 只有 `invalid_value` 类（截断等） |
| `stages` / `trail` | 三阶段全部 | `operator.add` | 只追加，任何情况下不清空 |

> `parse` 与 `extract` **不写** `fields`。这是硬约束（spec: `解析加抽取` Scenario），否则未经三分类的原始值会因为"看起来有值"被下游当可用数据。

## 2. 职责边界

**做**：把原始材料变成系统可识别的范式数据，并把"每个值能否跳回原文"变成可判定的事实。

**不做**：

| 不做 | 归谁 |
|---|---|
| 补原文没有的内容 | 谁都不做 —— 硬约束 |
| 判断金额是否合理、材料是否齐全、必填字段该不该阻断 | Agent 2（`stage.validate`） |
| 判断合规 | Agent 3 |
| 改写、润色、概括、摘要 | 谁都不做 |
| 修改 `Finding.blocking` | `requirements.yaml` 声明，Agent 4 也不得改 |

> **"不修改、不拓展关键信息"的可执行形式**：对原文的每一次读取、转换、放行都必须写 `TrailEntry`。
> `summarize` / `rewrite` / `drop` 三种 op 出现即视为越界，Agent 4 报 `fail`。
> 这不是靠 prompt 里写"请不要改写"实现的，是靠日志可查。

**Agent 1 会产 `Finding`**（`source="normalization"`，前缀 `N-`），但只限 `kind="invalid_value"`：
值超长被截断、值形态无法规范化。
**字段缺失、材料不齐不产 Finding** —— 那是 Agent 2 的判定，Agent 1 只负责把 `status="missing"` 如实标出来。

## 3. 输入

| 来源 | 形态 | `ParsedDoc.form` | 处理路径 |
|---|---|---|---|
| 客户邮件 | 纯文本正文 + 附件 | `email` | 正文进 block，附件逐个解析 |
| 单据 PDF | 文本型 PDF | `pdf_text` | 段落 + 页码 |
| 合同 / 要约 | 长文本 PDF | `pdf_text` | 同上，注意上下文预算 |
| 表格型申请表 | 表格型 PDF | `pdf_form` | **POC 不实现**，见 §3.1 |
| 粘贴文本 | 纯文本 | `plain_text` | 直接分段 |

### 3.1 表单型输入（扩展位，不是遗漏）

- 契约已预留 `Source.form_label`，自由文本路径恒为 `None`
- POC 表达方式：表单型 PDF 走自由文本路径，文本层可读则正常抽取，栏目名记入 `FieldValue.label`
- 表单路径需要的能力（栏目名识别、表格结构还原、栏目→`fields.yaml` 直接映射）**不在本 change 内**
- 演示时必须主动说明这是扩展位。客户问"我们银行的申请表能不能直接填"时，含糊其辞比说"下一期"更伤

## 4. 三个阶段

| 阶段 | 函数 | 调模型 | 纯函数 | 产出 |
|---|---|---|---|---|
| `parse` | `parse_file()` | 否 | 是 | `ParsedDoc`（blocks + full_text + errors） |
| `extract` | `extract()` | **是（唯一）** | 是 | `ExtractResult`（候选 + 待写 trail + 失败批次） |
| `normalize` | `build_fields()` / `detect_business_type()` | 否 | 是 | `NormalizeResult`（fields + extra + findings 草稿 + trail） |

**整个 Agent 1 只调一次模型，在 `extract`。** 其余全是确定性代码 —— 这样"同输入同输出"的范围尽可能大，也是现场能解释结论的前提。

节点层只做四件事：调纯函数、把 `trail` 写回、写 `StageReport`、把 `_candidates` 用后即清。**节点里不许有任何业务判定。**

## 5. `parse`

### 5.1 接口（最终）

```python
# app/parsing/parse.py
def parse_file(src: SourceFile) -> ParsedDoc: ...
```

返回单份 `ParsedDoc`，**不抛异常**：

- 单文件失败 → 该 doc 的 `errors` 非空，其余文件继续（`parse_node` 汇总为 `status="partial"`）
- 全部失败 → `parse_node` 写 `StageReport(status="failed")`，整次运行判 `fail`
- 无文本层 → `errors=["no_text_layer: 疑似扫描件，需 OCR（POC 不支持）"]`，**MUST NOT 返回空 `full_text` 当作解析成功**

### 5.2 `parse_errors` 为什么不进 state

旧版伪码 `return {"docs": docs, "parse_errors": errors}` 无处落地：`EditState` 没有这个键。本版裁决：

| 信息 | 落点 |
|---|---|
| 哪个文件为什么失败 | `ParsedDoc.errors`（契约已有） |
| 失败影响的阶段结论 | `StageReport(status="partial"/"failed", reason="…")` |
| 谁在什么时候读到了什么 | `TrailEntry(op="read")` + `detail.failed=[file_id…]` |

三层信息量都够，且**零新增键**。想加 `parse_errors` 的人请先看《编排层实施设计》§3.2 的裁决理由（新键会在 `reset` 循环里叠加）。

### 5.3 解析复用

`docs` 已存在且 `files` 的 `(file_id, sha256)` 集合完全一致 → **必须复用，不得重复解析**（契约：解析结果复用）。

复用时的阶段状态是 **`done` 不是 `skipped`**，理由写进 `reason="reused: 文件 sha256 未变化"`。
写 `skipped` 会让 `require()` / 闸门认为"解析没跑"，用户看到"解析未完成"却找不到原因。

## 6. `extract`

### 6.1 接口（纯函数，回执带 trail）

```python
# app/parsing/extract.py
@dataclass
class ExtractResult:
    candidates: list[dict] = field(default_factory=list)
    trail_entries: list[dict] = field(default_factory=list)
    model_calls: int = 0
    failed_batches: list[str] = field(default_factory=list)


def extract(docs: list[ParsedDoc], field_keys: list[str], *,
            llm, model: str = "gpt-4o", batch_chars: int = 12000) -> ExtractResult: ...
```

**为什么回执而不是直接写 state**：契约要求三函数可在无图状态下单测；同时"抽取必留痕"不能漏。
解法是纯函数把要记的 entry 带出来，由节点 `record_many()` 一次写回并分配 `TrailEntry.id`。
旧版伪码在 `extract()` 里直接 `record(state, …)`，`state` 根本不在作用域里 —— 那段代码跑不起来。

### 6.2 候选结构

```python
{
  "key": "guarantee_amount",
  "raw_value": "USD 500K",          # 模型输出，未规范化
  "label": "保函金额",               # 原文中的称呼，供核对台展示
  "confidence": 0.86,               # 仅本阶段排序用；**不写入 FieldValue**（契约无此字段）
  "doc_type": "application_form",
  "_source": {                      # 由 extract 组装，不是模型输出
     "file_id": "F-1a2b", "page": 2, "bbox": [72.0, 410.0, 480.0, 436.0],
     "span": "USD 500K", "form_label": None,
  },
}
```

`_source` 的下划线前缀含义同 `_candidates`：**节点/共享层内部结构，不是契约**。
`normalize` 消费后只把 `Source` 的五个键拷进 `FieldValue.source`；`confidence` 到此为止，绝不进契约。

### 6.3 分批：按 block 切，不按字符切

旧版用 `full_text[start:start+batch_chars]` 字符切片，会把一个金额切成 `USD 50` + `0K`，
两批各自得到一个错误候选，且**必然不可定位**（span 在原文里不连续）。

本版规则：

1. 按 `doc["blocks"]` 顺序累加，累计长度超过 `batch_chars` 就切一批（**不切断 block**）
2. 单个 block 本身超预算 → 单独成批，`detail={"oversize_block": true}`（模型可能看不清，但至少不会造出假候选）
3. 每批 `detail` 必须含 `{"file_id", "index", "range": [首 block 序, 末 block 序], "blocks": n}`

### 6.4 页码与 bbox 回填（本版新增，直接决定能不能跳原文）

模型只给 `span`，页码必须靠**回原文定位**得到；否则 `Source.page` 恒为 `None`，核对台"跳回原文"只能落到文件首页。

```python
# app/parsing/extract.py
def locate_span(doc: ParsedDoc, span: str) -> tuple[int | None, list[float] | None]:
    """在 doc.blocks 里定位 span，返回 (page, bbox)。定位失败返回 (None, None)。

    用 normalize_ws 比对（与 provenance_check 同一个函数，见 §7.1）。
    只接受**单一 block 内**命中：跨 block 的 span 属于 §7.2 的越界情形，
    这里返回 None 让它走"不可定位"分支，不要在两块之间猜一个 bbox。
    """
    needle = normalize_ws(span)
    if not needle:
        return None, None
    for b in doc["blocks"]:
        if needle in normalize_ws(b["text"]):
            return b["page"], b["bbox"]
    return None, None
```

**这是"能跳回原文"与"看起来有出处"的分界线**：`page=None` 的 `extracted` 字段在核对台里点不动，
而演示时客户的第一个动作就是点它。

### 6.5 prompt 硬约束（写进 prompt，不靠口头约定）

```text
1. 只允许逐字复制原文片段作为 span，禁止改写、禁止拼接跨段落内容。
2. span 是最小可定位片段，不要包含"申请人："这类栏目标签。
3. value 保持原文大小写与拼写，不要纠正、不要转大写。
4. 找不到的字段不要猜、不要编造，直接不输出。
```

### 6.6 重试与失败

- 输出不合 schema（`key` / `raw_value` / `span` / `confidence` 缺失或类型不符）→ **重试一次**
- 二次失败 → 该批计入 `failed_batches`，`extract_node` 写 `StageReport(status="partial", reason="n 个批次抽取失败")`
- 解析失败的文件 → 不抽取，但必须写一条 `op="pass"` + `detail.reason="该文件解析失败，未抽取"`（**不得静默 continue**）

## 7. `normalize`

### 7.1 `normalize_ws`：全层唯一的定位基准（权威规则清单）

**这一节是本 change 的核心。** Agent 1 用它判定 `status="extracted"` 是否成立，
Agent 4 的 `provenance_check` 用它校验 `extracted` 字段的 `span` 是否真在原文里。
**两份实现一旦分叉，全部字段会被判不合规，且原因极难定位**（契约：归一化规则必须共用）。

固定 5 步，**顺序不可调换**：

| 步 | 变换 | 处理什么 | 不处理会怎样 |
|---|---|---|---|
| 1 | `unicodedata.normalize("NFKC", s)` | 全角→半角、兼容字符→标准形（`：`→`:`、`（`→`(`、`１`→`1`、`ｍ`→`m`、`Ⅳ`→`IV`） | 中文全角标注的 PDF 里，模型复制的是全角，原文也是全角 —— 但只要一端被转过一次就全错 |
| 2 | 删除零宽与方向控制字符 | U+200B–U+200F、U+202A–U+202E、U+FEFF | PDF 抽取出的"\u200bABC"与"ABC"肉眼相同却比对不上 |
| 3 | 连字符归一 | U+2010 `‐`、U+2011 `‑`、U+2012、U+2013 `–`、U+2014 `—`、U+2015、U+2212 `−`、U+FE58、U+FE63、U+FF0D → `-` | 合同里的 `900‑1234`（非断行连字符）会让所有编号类字段变 `inferred` |
| 4 | 引号归一 | `‘’‚‛′‵` → `'`；`“”„‟″‶«»「」『』` → `"` | 名称里带引号（`"ABC" Trading`）时一律定位失败 |
| 5 | 空白折叠 + strip | 所有 Unicode 空白（含 U+3000、U+00A0、`\n`、`\t`）→ 单个半角空格 | 跨行 span 无法匹配（PDF 每行都是硬换行） |

**明确不做**（同样重要，否则两端又会分叉）：

| 不做 | 为什么 |
|---|---|
| 大小写折叠（`lower()`/`casefold()`） | 名称大小写是**事实**（接缝一）。模型若把 `ABC Trading` 抄成 `abc trading`，正应该判不可定位 —— 那是它没逐字复制 |
| 去标点、去空格 | 会掩盖模型拼接、改写，`provenance_check` 就失去意义 |
| 同义词、单位换算、简繁转换 | 属于业务判定（Agent 2），不是"是否指向同一段原文" |
| 正则去 HTML / 去页眉页脚 | 应该发生在 `parse`，不能在判定基准里偷偷做 |

```python
# app/parsing/normalize.py
import re
import unicodedata

MAX_SPAN_LEN = 200          # 与 agent-audit 的 provenance_check 共用同一常量

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")
_SINGLE_QUOTES = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032\u2035"), "'")
_DOUBLE_QUOTES = dict.fromkeys(map(ord, "\u201c\u201d\u201e\u201f\u2033\u2036\u00ab\u00bb\u300c\u300d\u300e\u300f"), '"')
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\ufeff]")
_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """全层唯一的"是否指向同一段原文"判定基准。5 步，顺序不可换。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _INVISIBLE.sub("", s)
    s = s.translate(_DASHES).translate(_SINGLE_QUOTES).translate(_DOUBLE_QUOTES)
    return _WS.sub(" ", s).strip()


def span_locatable(src: dict, docs: list) -> bool:
    """span 是否能在**它自己声明的那个文件**里定位。

    【为什么限定单一文件】provenance_check 是按 file_id 取全文比对的。
    若这里允许跨文件搜索，Agent 1 会标 extracted 而 Agent 4 判 fail —— 同一份数据两套结论。
    """
    text = {d["file_id"]: normalize_ws(d["full_text"]) for d in docs}.get(src.get("file_id", ""))
    needle = normalize_ws(src.get("span", ""))
    return bool(needle) and text is not None and needle in text
```

> 上一版只做了"空白折叠 + 5 个全角标点替换"，第 1/3/4 步全缺。
> 后果不是理论风险：**名称、编号、带引号的条款号会成批掉成 `inferred`**，而 `inferred` 占比是验收指标（§13）。

### 7.2 span 的最小片段边界（REVIEW 三问的正式答案）

**问题**：原文 `ABC TRADING PTE LTD（以下简称"申请人"）`，span 取到哪里？

**规则（5 条，按序判断，命中即停）**：

| # | 规则 | 例 |
|---|---|---|
| 1 | 不含栏目标签：span 左端若在原文中紧跟在 `：`/`:` 之后，取其后；右端若紧邻下一个标签的 `：`，截到其前 | `申请人：ABC TRADING PTE LTD 地址：新加坡` → `ABC TRADING PTE LTD` |
| 2 | 遇注释性开括号即截断，括号本身不入 span | `ABC TRADING PTE LTD（以下简称"申请人"）` → `ABC TRADING PTE LTD` |
| 3 | 遇同层分隔符截断：`，` `,` `；` `;` `。` `|` 以及两个以上空格 | `金额 USD 500K，期限 720 天` → `USD 500K` |
| 4 | 长度上限 `MAX_SPAN_LEN = 200`。超长先按句末标点切到 ≤200；切不出（单句超 200）→ 保留整段但 `notes=["span_oversize"]` 且 `status="inferred"` | 整段条款不得作为 `extracted` 的出处 |
| 5 | 跨行允许，跨页降级：同一页相邻 block 的软换行可以拼（`normalize_ws` 会折叠成空格）；**跨页拼接必须 `notes += ["merged_across_pages"]` + `op="transform"` + `detail={"cross_page": true, "pages": [...]}`，且 `status` 降为 `inferred`** | 表格跨页的两行拼成一个值 |

**为什么第 4 条上限是 200**：子串匹配无法区分"最小片段"与"抓整行蒙混"，长度是唯一可判定的代理指标。
`provenance_check` 对 `len(span) > MAX_SPAN_LEN` 报 `warn`，Agent 1 必须在源头就不产出这种 span，
否则每份文档都会固定产出十几条 warn，warn 就失去意义。

**span 绝不允许被截断**：截断 span 会让 `provenance_check` 直接 `fail`（截断后的片段可能仍能匹配，也可能不能，
两种结果都是错的）。要截断的是**值**（§7.5），不是出处。

### 7.3 值规范化规则

| 类型 | 规则 | 例 | `normalized_from` | 降级 |
|---|---|---|---|---|
| `amount` | `Decimal`，2 位小数，去千分位与币种前缀 | `USD 500K` → `500000.00`；`1,200,000.00` → `1200000.00` | 原值 | 非数字 → `amount_not_numeric` + `inferred` |
| `currency` | ISO 4217 三位大写 | `usd` → `USD` | 原值 | 非三位 → `currency_not_iso4217` + `inferred` |
| `date` | ISO 8601 | `2026-12-31`；`2026/12/31` → `2026-12-31` | 原值 | 见下"日期歧义" |
| `date`（歧义） | 按字段 `date_order` 解释；未声明 → 保持原值 | `12/03/26` | 原值 | `date_ambiguous` + `inferred` |
| `integer` | 去单位后缀（仅当字段名/`unit` 已声明） | `720 DAYS`（字段 `tenor_days`）→ `720` | 原值 | 无法解析 → `not_numeric` + `inferred` |
| `country` | ISO 3166-1 alpha-2 大写 | `sg` → `SG` | 原值 | 无法映射 → `country_not_iso3166` + `inferred` |
| `string`（名称类） | **仅去首尾空白**，不改大小写与拼写 | ` ABC Trading Pte Ltd ` → `ABC Trading Pte Ltd` | 原值 | — |
| `string`（地址/条款） | 折叠连续空白，不改写 | — | 原值 | — |

**金额必须用 `Decimal`**，不得用 `float`：`0.1+0.2` 在闸门与前端显示上会变成 `0.30000000000000004`，
这类数字出现在客户面前的代价远大于多写一行 `Decimal`。

**名称不 `upper()`** 的理由：名称一致性比对由 Agent 2 负责，比对时双方各自归一化；
Agent 1 一旦提前大写，`normalized_from` 之外的原始形态就丢了，而合规场景要展示的正是客户原文。
统一约定见 `agent-contract` 的接缝一。

### 7.4 三分类判定（含上一版缺失的 `missing`）

```python
# app/parsing/normalize.py
DOWNGRADING_NOTES = frozenset({
    "date_ambiguous", "amount_not_numeric", "currency_not_iso4217",
    "country_not_iso3166", "not_numeric", "span_oversize",
    "merged_across_pages", "value_truncated",
})


def classify(value: str | None, locatable: bool, notes: list[str]) -> str:
    """三分类。**只有这三条分支**，任何一处想加特例都要先改 spec。"""
    if value is None or value == "":
        return "missing"
    if locatable and not (DOWNGRADING_NOTES & set(notes)):
        return "extracted"
    return "inferred"
```

| 判定 | 条件 | 下游含义 |
|---|---|---|
| `extracted` | span 在本文件内可定位 **且** 无降级 note | MAY 免人工核对（契约接缝一） |
| `inferred` | 不可定位，或带任一降级 note | MUST 人工确认，`confirmed` 保持 `false` |
| `missing` | 值为空，或 `required` 字段根本没有候选 | 原文没写 / 没抽出来 —— 但**不由此判定阻断** |

**`missing` 占位（本版新增，修掉一个死枚举）**

旧版 `build_fields` 只遍历候选，没有候选的字段在 `fields` 里**根本不存在**。
后果：① `missing` 这个枚举值永远不会出现；② Agent 2 与闸门无法区分"原文没写"与"没抽出来"；
③ 核对台只显示 `fields` 里的键，客户说"我这栏明明写了"时无从解释。

规则：

1. 遍历 `fields.yaml` 全部字段，**`required: true` 且没有候选** → 写一条占位：

```python
fields[key] = FieldValue(
    key=key, value=None, status="missing", confirmed=False, edited_by_user=False,
    source=None, normalized_from=None, label=fdef.get("label"), doc_type=None,
    notes=["not_in_source"])
```

2. 每个占位必须写一条 `op="pass"` 留痕，`detail={"key": key, "reason": "原文未出现该字段"}` ——
   "没找到"也是一次操作，也必须可查
3. **非必填字段缺失不占位**：占位是为了让人看见"该有却没有"，可选字段占位只会把核对台刷满
4. `required` 未显式声明的字段**按可选处理**（`fields.yaml` 里 `required` 必须写，不许缺省）
5. 占位**不产 Finding**：`status="missing"` 是事实陈述，"该不该阻断"由 Agent 2 按 `requirements.yaml` 判

### 7.5 截断与 `N-` Finding

`max_length` 在 `fields.yaml` 里属于 `stage.normalize`（见 §7.7），Agent 1 必须执行：

```python
if fdef.get("max_length") and len(val) > fdef["max_length"]:
    original = val
    val = val[: fdef["max_length"]]
    notes.append("value_truncated")
    findings.append({                      # 草稿：**不带 id**，由节点统一编号
        "source": "normalization",
        "kind": "invalid_value",
        "rule_id": f"F-{key}-max_length",
        "severity": "warn",
        "blocking": False,                 # 恒为 False：blocking 只由 requirements.yaml 声明
        "resolved": False,
        "resolution": None,
        "field_keys": [key],
        "message": f"{key} 长度 {len(original)} 超过 fields.yaml 上限 "
                   f"{fdef['max_length']}，已截断，请人工确认",
        "evidence": original[:80],
        "citation": None,
        "suggestion": "请核对原文该栏是否确实超长，必要时在核对台修正",
    })
```

三件事必须同时发生，缺一不可：**截断值**（否则脏值会流到下游）、
**`notes=["value_truncated"]` + `status="inferred"`**（截断是信息丢失，不能算 `extracted`）、
**一条 `N-` Finding**（否则截断静默发生，客户永远不知道）。

**ID 由节点分配，纯函数不编号**（`app/findings.py`）：

```python
# app/findings.py
from app.state import FINDING_PREFIX, Finding


def materialize_findings(state: dict, drafts: list[dict]) -> dict:
    """给草稿编号 + 写 emit 留痕。返回 {"findings": [...], "trail": [...]}。

    【为什么不在纯函数里编号】next id 依赖 state["findings"]，而 build_fields() 是纯函数。
    编号与留痕放到这里，Agent 2 / Agent 3 复用同一实现，三个前缀不会互相撞号。
    """
    out_findings: list[Finding] = []
    out_trail: list[dict] = []
    counters: dict[str, int] = {}
    for f in state.get("findings", []):
        prefix, _, tail = str(f.get("id", "")).partition("-")
        if tail.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(tail))

    for draft in drafts:
        prefix = FINDING_PREFIX[draft["source"]]
        counters[prefix] = counters.get(prefix, 0) + 1
        fid = f"{prefix}-{counters[prefix]:03d}"
        out_findings.append(Finding(id=fid, **draft))
        out_trail.append({
            "agent": "agent1", "stage": "normalize", "op": "emit",
            "after": fid, "ref": ",".join(draft.get("field_keys") or []),
            "detail": {"rule_id": draft["rule_id"], "kind": draft["kind"]},
        })
    return {"findings": out_findings, "trail": out_trail}
```

### 7.6 `business_type` 判定（唯一写入者）

依据优先级：**文档明确声明 > 字段组合特征 > 无法判定**。判决表（顺序执行，命中即停）：

| 步 | 判据（在 `normalize_ws(full_text)` 上做） | 结果 | `detail.reason` |
|---|---|---|---|
| 1 | 命中强指示词：`URDG 758`、`独立保函`、`见索即付`、`BANK GUARANTEE` | `guarantee` | `explicit_independence_clause` |
| 2 | 命中一般词：`保函`、`GUARANTEE` | `guarantee` | `explicit_keyword` |
| 3 | 未命中上述，但命中其他已知类型：`INVOICE`/`发票`/`CONTRACT`/`合同`/`BILL OF LADING`/`提单` | `unsupported` | `business_type_not_supported` |
| 4 | 都不命中 | `unsupported` | `no_evidence` |

- 每条分支**必须**写一条 `op="pass"` 留痕：
  `detail={"business_type": …, "evidence": "<命中原文片段≤80>", "file_id": …, "reason": …}`
- 步 1 命中后**不得**再被步 2/3 覆盖（合同里提到"保函"是常态，属于同一业务）
- 步 4 **MUST NOT** 为了保证下游能跑而强行选一个类型 —— `unsupported` 会让 Agent 2/3 走
  "业务类型不确定"分支，这是正确行为，不是故障
- **唯一写入者**：只有 `normalize` 写 `EditState.business_type`。`ingest` 只透传已有值（重跑不改判定），
  Agent 3 在 `raw` 模式下推断的类型只写 `legal.coverage`（契约接缝二）

### 7.7 `fields.yaml`：约束归属的最终裁决

```yaml
- key: guarantee_amount
  label: 保函金额                 # 原文中该字段的常见称呼
  aliases: ["金额", "AMOUNT", "保函金额"]
  type: amount                    # amount / currency / date / integer / string / country
  required: true                  # A 读它决定是否补 missing 占位；B 用它判阻断
  date_order: null                # 仅日期类字段使用：DMY / MDY / null
  stage:
    normalize: [precision, thousands, max_length]   # A：怎么转成合规形式
    validate:  [required, positive]                 # B：业务上允不允许
  max_length: 18
  charset: '0-9.'
```

| 约束 | 归属 | 谁执行 | 说明 |
|---|---|---|---|
| `precision` / `thousands` | normalize | A | 金额形式 |
| `max_length` / `charset` | normalize | A | 形式约束；超长截断见 §7.5（上一版把 `max_length` 放在顶层却没写进 `stage`，"截断是谁的责任"无人认领） |
| `date_order` | normalize | A | 决定 `DD/MM` 还是 `MM/DD` |
| `required` | validate | B | **A 只读不判**：读到 `true` 才补 `missing` 占位，阻断结论由 B 产 Finding |
| `positive` / `range` / 业务规则 | validate | A **不得**执行 | 执行即跨了接缝 |

**职责分离的判定方法**（写进 code review checklist）：
问"这条约束违反了，是'系统没读懂'还是'业务不允许'？"前者归 A，后者归 B。
`required` 是唯一一个 A 需要**读**（但不能执行）的 `validate` 约束，因为它决定要不要补占位。

## 8. 输出

| 键 | 内容 | 谁写 |
|---|---|---|
| `docs` | `list[ParsedDoc]` | `parse_node` |
| `fields` | `dict[str, FieldValue]`，仅 `fields.yaml` 内的键（含 `missing` 占位） | `normalize_node` |
| `extra_fields` | `dict[str, FieldValue]`，字典外字段，**不得混入 `fields`** | `normalize_node` |
| `business_type` | `guarantee` / `unsupported` | `normalize_node`（唯一） |
| `findings` | `N-` 前缀，仅 `invalid_value` 类 | `normalize_node` |
| `stages` / `trail` | 每阶段 / 每条操作 | 三个节点 |

**`_candidates` 的生命周期**（临时通道，不进契约）：

| 时刻 | 谁 | 做什么 |
|---|---|---|
| `extract` 返回后 | `extract_node` | 写入 `_candidates` |
| `normalize` 开始时 | `normalize_node` | 读取并消费 |
| `normalize` 返回时 | `normalize_node` | `{"_candidates": Overwrite([])}` **必须清空**，否则被 checkpointer 长期保存 |
| 独立触发只跑 `parse → extract` | 调用方 | 可以读到 `_candidates`，但**不得**当 `fields` 用 |

## 9. 失败与降级

| 场景 | 表现 | 降级 | 谁承担 |
|---|---|---|---|
| 单文件解析失败 | `ParsedDoc.errors` 非空 | 该文件不参与后续，其余继续 | `parse_node` → `status="partial"` |
| 全部文件失败 | `docs=[]` | `fields={}`，`status="failed"`，整次运行 `fail` | `parse_node` |
| 扫描件（无文本层） | `errors=["no_text_layer: …"]` | 明确提示"扫描件不支持"，**不得返回空 `full_text` 伪装成功** | `parse_node` |
| `extract` 输出不合 schema | 重试一次 | 二次失败 → `status="partial"` + `failed_batches` | `extract_node` |
| 某字段值超长 | 截断 + `notes=["value_truncated"]` + `status="inferred"` + `N-` Finding(`warn`) | 人工确认 | `normalize_node` |
| 日期歧义 | `notes=["date_ambiguous"]` | `status="inferred"`，保持原值不猜 | `normalize_node` |
| `required` 字段无候选 | `status="missing"` + `notes=["not_in_source"]` | 交 Agent 2 判阻断 | `normalize_node` |
| 业务类型无法判定 | `business_type="unsupported"` + trail 记依据缺失 | 下游走"类型不确定"分支 | `normalize_node` |
| `fields.yaml` 缺失/读不出 | 三阶段全部 `status="failed"`，`reason="fields.yaml 不可用"` | 整次运行 `fail` | 启动期校验 |

> 最后一行是上一版没写的坑：`fields_yaml.get("fields", {})` 在缺文件时返回 `{}`，
> 于是全部字段静默进 `extra_fields`、`fields` 为空、下游全部 `missing` —— 一次配置事故会伪装成"材料没写"。
> **配置在启动时校验**，不要靠运行时的默认值兜底。

## 10. 独立触发：三档

| 档 | `stages` 参数 | 执行链 | 产出 | **不得产出** |
|---|---|---|---|---|
| 只解析 | `parse` | `parse` | `docs` + `stages` + `trail` | `fields` / `extra_fields` / `business_type` |
| 解析 + 抽取 | `extract` | `parse → extract` | `docs` + `_candidates` + `stages` + `trail` | `fields`（未经三分类与规范化，**不满足契约**） |
| 完整 | `normalize` | `parse → extract → normalize` | 上述 + `fields` / `extra_fields` / `business_type` / `N-` findings | — |

三档必须登记为 `AGENT_SPECS` 的 stage target（`parse` / `extract` / `normalize`），
否则 `plan_standalone()` 直接返回 `409 unknown_stage`，本 change 的三个 Scenario 无法验收。
见《编排层实施设计》§4.1（声明表）与 §11.1（补跑矩阵）。

**"只跑到 extract 不写 fields" 是硬约束**，不是保守：候选值没有规范化、没有三分类、没有出处校验，
写进 `fields` 就等于给下游一个"看起来可用"的假数据。
前端需要预览时读 `_candidates`，并明确标注"未规范化、不可用于核对"。

## 11. 留痕清单（每份材料至少这些 entry）

| 时机 | `op` | 必填字段 | 备注 |
|---|---|---|---|
| 解析成功 | `read` | `after="n docs / m blocks"`, `detail.failed` | 有失败文件也必须记 |
| 解析复用 | `pass` | `detail={"reuse": true, "reason": …}` | 复用不是"没跑" |
| 每批抽取 | `llm_call` | `model`, `prompt_hash`, `detail.range` | 长文档多批各记一条 |
| 每候选 | `emit` | `before=span`, `after=raw_value`, `ref=file_id/page` | 抽取产出可追溯 |
| 每字段规范化 | `transform` | `before=raw_value`, `after=value`, `detail.key/status/notes` | 形式变更留证 |
| 每 `missing` 占位 | `pass` | `detail.key`, `detail.reason` | "没找到"也是操作 |
| 值截断 | `emit` | `after=N-xxx`, `detail.rule_id` | 与 Finding 一一对应 |
| 业务类型判定 | `pass` | `detail.business_type/evidence/reason` | 含"无法判定"分支 |
| 解析失败未抽取 | `pass` | `detail.reason`, `detail.errors` | **绝不能静默 continue** |

全流程 `trail` 中 **MUST NOT** 出现 `summarize` / `rewrite` / `drop`（验收第 4 项）。

## 12. 测试

```text
tests/test_parse.py                                  # 解析行为（实现由共享层提供）
  test_pdf_blocks_have_page
  test_plain_text_blocks_have_no_page
  test_scan_like_pdf_raises_not_silent
  test_partial_failure_continues
  test_same_pdf_two_paths_identical_blocks

tests/test_normalize.py                              # 值规范化 + 三分类
  test_amount_normalized_from_preserved
  test_currency_iso4217
  test_date_ambiguous_downgraded_to_inferred         # date_order 缺省
  test_date_order_dmy_resolves_without_note
  test_name_case_preserved
  test_span_not_found_becomes_inferred
  test_span_found_in_other_file_becomes_inferred     # 不允许跨文件定位
  test_span_whitespace_normalized_match              # 跨行 span 可定位
  test_normalize_ws_nfkc_dashes_quotes               # 全半角 / U+2011 / 弯引号
  test_undefined_field_goes_to_extra_fields
  test_oversize_field_truncated_with_finding         # 截断 + notes + N-001
  test_finding_ids_continue_after_rerun              # 重跑不撞号
  test_required_missing_gets_placeholder             # status=missing + notes
  test_optional_missing_not_present                  # 可选字段不占位
  test_span_oversize_downgrade
  test_cross_page_span_downgrade

tests/test_business_type.py
  test_explicit_urdg_758_is_guarantee
  test_no_evidence_is_unsupported_not_guessed
  test_invoice_only_is_unsupported
  test_decision_recorded_in_trail

tests/test_agent1_trail.py                           # 留痕
  test_every_extracted_field_has_trail_entry
  test_skipping_pages_recorded_as_pass
  test_llm_call_has_model_and_prompt_hash
  test_no_overreach_ops_in_full_run                  # summarize/rewrite/drop 计数为 0
  test_rerun_keeps_append_only_trail                 # 重跑后 trail 只增不减

tests/test_agent1_standalone.py                      # 三档独立触发
  test_parse_only_does_not_write_fields
  test_extract_only_does_not_write_fields
  test_unknown_stage_refused                         # 未登记的 target 必须 409
```

## 13. 验收（对齐《编排层实施设计》§18.3 与 tasks §11）

| # | 验收项 | 判定方法 |
|---|---|---|
| 1 | 3 份样本端到端跑通，`fields` 非空 | `Runner.run` 后 `fields` 与 `stages` 均存在 |
| 2 | 每个 `extracted` 字段的 `span` 能人工在原文中搜到 | 抽查 20 个，`provenance_check` 零 fail |
| 3 | `inferred` 占比 < 30% | `count(status=="inferred") / len(fields)` |
| 4 | 全流程 trail 无 `summarize` / `rewrite` / `drop` | `overreach_entries(state) == []` |
| 5 | 名称类字段大小写与原文一致 | 抽 20 个对照原文 |
| 6 | 每个 `extracted` 字段 `source.page` 非空（PDF 输入） | 抽检；`page=None` 说明 bbox 回填没做 |
| 7 | `required` 缺失时 `status="missing"` 而非字段不存在 | 造一份缺金额的材料 |
| 8 | 超长值：截断 + `notes` 有 `value_truncated` + 存在 `N-` Finding | 造一份超 18 字符的金额 |
| 9 | 只跑 `parse → extract` 后 `fields` 仍为空 | 断言 `"fields" not in state` |
| 10 | `business_type` 只由 `normalize` 写入 | 全图搜索写入点，只允许一处 |

## 14. 明确不做 + 待确认

**不做**（本 change 之外）：OCR / 扫描件、表单结构还原、多业务类型字段集切换、
字段级 `confidence` 进入契约、跨文件 span 拼接、`normalize_ws` 之外的任何"语义等价"判定。

**待确认**（阻塞验收，需在契约冻结前拍板）：

| # | 问题 | 影响 | 需谁定 |
|---|---|---|---|
| 1 | `MAX_SPAN_LEN = 200` 是否够用（长条款号、地址可能天然超长） | 超长即 `warn`，会拉低 `provenance_coverage` | A + C |
| 2 | `required` 由 A 读取是否算违反"只执行 `stage=normalize`" | 若禁止，`missing` 占位无法产生 | A + B |
| 3 | `business_type` 词表是否需要业务确认（`见索即付` 等强指示词） | 判错类型会让 Agent 2/3 走错分支 | 业务方 + A |
