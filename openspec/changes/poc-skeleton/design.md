# Design: POC 骨架与契约冻结（v2）

> **契约真相源**：本文件。实现时 `app/state.py` 必须与本文件逐字段一致；两者不一致以本文件为准。
> **上位依据**：`design/TradeAI_需求设计_v2/Implements_doc/Orchestrator_Agent_Layer_实施设计.md`
> （下称《实施设计》）。本文件只裁决 POC 必须落地什么，不复制其实现细节；与其冲突时以它为准，
> 并把结论回写 §5 的裁决表。
> **命名陷阱**：`agent-verify` = Agent 2（前缀 `B-`）；`agent-audit` = Agent 4（目录 `app/verifier/`）；
> `benchmark` 禁止指代 Agent 4（历史命名残留）；`merge` 只排序去重、不重新编号；
> `reset` 不清 `stages` / `trail`；`pass`（op）≠ `pass`（gate verdict）；`partial` 必须阻断导出。

## 0. 阅读指引

| 读者 | 读哪些 | 时长 |
|---|---|---|
| A / B / C（只关心接缝） | `specs/agent-contract/spec.md` | 30 min |
| 要写代码 | §2 → §3 → §4 → §6 → §10 | 2 h |
| 做 code review | §5（裁决表）→ §9（节点不变量）→ §14（测试） | 1 h |
| 组织验收演示 | §14 + §15 | 20 min |

## 1. 目标与非目标

**目标**：把"三人并行写四个 Agent"从口头约定变成可编译、可测试、可判定的接缝 ——
一份契约（§4）、一份职责矩阵（§3）、一份前置声明（§7）、四对 fixture（§14）、
一条能走到 `export` 的主图（§10）。

**非目标**：四个 Agent 的真实业务逻辑、RAG、检查器集合、前端、OCR、表单结构还原、真实法规库、
跨单据比对。占位 subgraph 只保证**结构正确 + 留痕非空**，不产出任何业务结论。

**贯穿全 change 的判断标准**：任何"看起来成功了"的路径，都必须能在数据结构上被证伪。
由此推出三条不可让步的实现要求：

1. 空 `findings` **不得**单独作为放行依据（必须先看 `StageReport`）
2. `verification.score` 只展示，**不得**参与阻断或重跑
3. 前置缺失时**拒绝**，不得返回空结果

## 2. 目录结构、Owner 与冻结级别

```text
app/
  state.py               契约                      Orchestrator  **冻结（三人签字）**
  stages.py              阶段登记 / 前置拒绝         Orchestrator  **冻结（签名）**
  trail.py               留痕（record / record_many） Orchestrator  **冻结**
  findings.py            Finding 编号 + emit 留痕   Orchestrator  **冻结（三 Agent 共用）**
  parsing/
    parse.py             SourceFile -> ParsedDoc    A  签名冻结，实现自由
    extract.py           ParsedDoc -> ExtractResult A  签名冻结（唯一模型入口）
    normalize.py         NormalizeResult / normalize_ws / MAX_SPAN_LEN  A  签名冻结
  nodes/                 ingest reset merge gate export hitl repair  Orchestrator  自由
  graph.py               主图节点与边              Orchestrator  **节点名 / 边冻结**
  graph_factory.py       建图 + checkpointer        Orchestrator  自由
  standalone.py          独立触发补跑计划            Orchestrator  **冻结（矩阵见 §13）**
  store.py / runner.py   POC 控制平面（SQLite）      Orchestrator  对外接口冻结
  api/main.py            HTTP 层                    Orchestrator  自由
  storage/doc_versions.py 导出不可变版本             Orchestrator  自由
  agents/normalize/      Agent 1                    A  自由（只受接缝约束）
  agents/verify/         Agent 2                    B  自由（只受接缝约束）
  agents/regulatory/     Agent 3                    C  自由（只受接缝约束）
  verifier/              Agent 4 框架 + 检查器       C（A 出一支）签名 `(state) -> list[Issue]`
fixtures/seam_*          四对接缝 fixture            全员  **冻结（改 = 改契约）**
```

### 为什么 `parsing/` 是共享层

`agent1` 不是这些步骤的私有者。独立触发 Agent 3（用户直接扫原始文档、不等 Agent 1）同样需要
`parse`；"只跑要件校验"同样需要 `extract`。若各写一份，同一份 PDF 会切出不同段落、`evidence`
指向不同位置，演示时出现"同一文档两次扫描结论不同"且无法解释。

**因此 `parse` / `extract` / `normalize` 只有一份实现，任何 Agent 通过声明前置阶段来组合它们。**

### 为什么 `findings.py` 也是共享文件

编号与 `emit` 留痕各写一份时，`merge` 的"前缀必须与 `source` 匹配"这条校验会漏检，回放里也分不清
`N-003` 出自哪个阶段。《实施设计》附录 A 已把它列为冻结文件。

## 3. 职责矩阵：谁写哪个 state 键

> 这张表是**并行安全的唯一依据**。加新键前先在这里登记，否则并行分支会静默覆盖。

| state 键 | 写入者 | reducer | 读取者 |
|---|---|---|---|
| `run_id` / `files` | `ingest` | 无 | 全体 / `parse` / `agent3(raw)` |
| `business_type` | **`normalize`（唯一写入者；`ingest` 只透传）** | 无 | `agent2` / `agent3` / `gate` |
| `docs` | `parse`（共享层） | 无 | `extract` / `agent3` / `agent4` |
| `fields` / `extra_fields` | `normalize`（共享层） | 无 | `agent2` / `agent3` / `gate` / `hitl` |
| `_candidates` | `extract` 写 / `normalize` 清 | 无 | `normalize`（**临时通道，不进契约**） |
| `findings` | `agent1` / `agent2` / `agent3` | **add** | `merge` / `agent4` / `gate` / `hitl` |
| `legal` / `retrieved` | `agent3` | 无 | `agent4` / `gate` / `hitl` |
| `trail` | 全体 | **add** | `agent4` / 回放 |
| `stages` | 全体 | **add** | `gate` / 独立触发 / 回放 |
| `verification` | `agent4` | 无 | `gate` / `hitl` / `repair` |
| `gate` / `export` | `gate` / `export` | 无 | `export` / API |
| `recheck` / `recheck_count` | `hitl` | 无 | `route_after_hitl` |
| `repair_count` | `repair` | 无 | `route_after_verifier` |
| `requested_stages` | 控制平面写初始 state | 无 | 独立触发 |

`agent2` 与 `agent3` 在**同一超级步并行**，写集交集只有 `findings` / `trail` / `stages` ——
恰好是三个带 reducer 的键。这不是巧合而是契约设计的结果：
**任何新的并行写入键都必须先加 reducer 并经三人同意。**

## 4. 契约（`app/state.py`）

### 4.1 枚举常量（运行时用常量，禁止手拼字符串）

```python
AGENT_IDS = ("agent1", "agent2", "agent3", "agent4")
STAGE_STATUS = ("done", "skipped", "partial", "failed")
FINDING_SOURCES = ("normalization", "business", "regulatory")
FINDING_KINDS = ("missing", "not_found", "invalid_value", "inconsistent",
                 "policy_violation", "regulatory_risk", "trail_violation")
SEVERITIES = ("critical", "warn", "info")
TRAIL_OPS = ("read", "llm_call", "transform", "emit", "pass",
             "summarize", "rewrite", "drop")
OVERREACH_OPS = frozenset({"summarize", "rewrite", "drop"})        # 越界信号
FINDING_PREFIX = {"normalization": "N", "business": "B", "regulatory": "R"}
SHARED_STAGE_OWNER = "agent1"        # 共享阶段（parse/extract/normalize）的归因 agent
```

> `StageReport.agent` 只允许 `agent1..4`，而 `parse` / `extract` / `normalize` 不是 Agent，
> 因此共享阶段的报告统一记在 `SHARED_STAGE_OWNER` 名下，回放时才有唯一归因。

### 4.2 解析产物

```python
class ParsedBlock(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None          # [x0, y0, x1, y1]；纯文本为 None
    text: str                         # 原文，未做任何改写
    kind: Literal["paragraph", "table_cell", "header", "footer"]

class ParsedDoc(TypedDict):
    file_id: str
    filename: str
    mime: str
    form: Literal["pdf_text", "pdf_form", "email", "plain_text"]
    blocks: list[ParsedBlock]
    full_text: str                    # blocks 按序拼接，Agent 3 直接消费
    errors: list[str]                 # 解析失败原因；非空时该文件不参与后续
    sha256: NotRequired[str | None]   # 【语义】docs 复用判定用，见接缝二
```

### 4.3 出处与字段值

```python
class Source(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None
    span: str                         # 【语义】最小可定位片段，不含"申请人："之类 label
    form_label: str | None            # 表单栏目名；自由文本恒为 None（POC 不实现表单路径）

class FieldValue(TypedDict):
    key: str                          # 来自 fields.yaml
    value: str | None                 # 【语义】规范化后的值，大小写与拼写照原文
    status: Literal["extracted", "inferred", "missing"]
    confirmed: bool                   # 用户是否已在核对台确认
    edited_by_user: bool              # 用户是否手工改过值
    source: Source | None
    normalized_from: str | None       # 规范化前的原值，原样保留
    label: str | None                 # 原文中该字段的原始称呼
    doc_type: str | None              # invoice / contract / bl / application_form …
    notes: list[str]                  # 歧义、截断等说明，如 "date_ambiguous"（空为 []）
```

**三分类语义（必须按此实现，否则 `missing` 是死枚举）**

| status | 判据 | 下游可做 |
|---|---|---|
| `extracted` | 值能按共享 `normalize_ws` 在**该 `file_id` 的全文**定位 | 可免除人工核对 |
| `inferred` | 值来自跨字段推断 / 跨页拼接 / 超长截断等 | 必须人工确认，否则 `gate` 阻断 |
| `missing` | `fields.yaml` 标 `required: true` 且**无任何候选** → 占位 `value=None`、`notes=["not_in_source"]`，并记一条 `op="pass"` | 区分"原文没写"与"没抽出来" |

### 4.4 审查结论

```python
class Finding(TypedDict):
    id: str                            # N-001 / B-001 / R-001（各 Agent 命名空间内自增）
    source: Literal["normalization", "business", "regulatory"]
    kind: Literal["missing", "not_found", "invalid_value", "inconsistent",
                  "policy_violation", "regulatory_risk", "trail_violation"]
    rule_id: str
    severity: Literal["critical", "warn", "info"]
    blocking: bool                     # 由 requirements.yaml 规则声明，不由 severity 推导
    resolved: bool                     # 新产出恒为 False；只有 hitl 可改
    resolution: str | None             # 新产出恒为 None
    field_keys: list[str]              # 【语义】无关联字段时为空列表，不是 None
    message: str
    evidence: str | None               # 必须是原文片段或字段值，不得为空泛描述
    citation: str | None               # chunk_id，仅 regulatory
    suggestion: str | None
    confidence: NotRequired[float]     # 同类判定冲突时降权；仅展示与排序，不参与阻断
    needs_review: NotRequired[bool]    # 双判冲突等需人工看一眼的条目
```

> `confidence` / `needs_review` 是《实施设计》§3.2 裁决新增的**可选**字段：
> 契约规定"子结构只增不改，新增必须可选"，因此 fixture 无需改写。

### 4.5 Agent 3 输出

```python
class Claim(TypedDict):
    text: str
    chunk_id: str | None               # None = 依据不足
    kind: Literal["applicable_rule", "risk", "condition"]
    support: Literal["supported", "insufficient"]

class ApplicableRule(TypedDict):
    rule_id: str
    title: str
    version: str
    effective_from: str | None
    chunk_id: str

class LegalOpinion(TypedDict):
    input_mode: Literal["enriched", "raw"]   # raw = 没跑 extract，下游不得做 conflict_check
    applicable_rules: list[ApplicableRule]
    claims: list[Claim]
    coverage: dict                     # {jurisdictions, standards, unavailable,
                                       #  business_type_uncertain, notes}
    escalate_to_human: bool
    summary: str
```

### 4.6 阶段记录与操作日志

```python
class StageReport(TypedDict):
    stage: str                         # "parse" / "agent2.check_rules" / "gate" …
    agent: Literal["agent1", "agent2", "agent3", "agent4"]   # 共享阶段记 SHARED_STAGE_OWNER
    status: Literal["done", "skipped", "partial", "failed"]
    reason: str | None                 # skipped/failed/partial 必填
    produced: int                      # 本次产出的条目数
    model_calls: int

# 【语义】produced=0 且 status="done"  = 检查过，没问题
#        produced=0 且 status!="done" = 没检查（下游不得推断为"未发现问题"）

class TrailEntry(TypedDict):
    id: str                            # "agent1.extract#003"，agent 内自增，避免并行冲突
    agent: Literal["agent1", "agent2", "agent3", "agent4"]
    stage: str
    op: Literal["read", "llm_call", "transform", "emit", "pass",
                "summarize", "rewrite", "drop"]   # 后三者 = 越界信号
    before: str | None                 # 原文片段
    after: str | None                  # 产出值
    ref: str | None                    # "file_id/page/span" 或上一条 entry 的 id
    model: str | None
    prompt_hash: str | None
    detail: dict
```

**`stages` 只能追加，读的时候取同名阶段的最后一条**（`latest_stage()`）。理由：重跑后同名报告会有
多条，"用户改了字段之后第二次跑失败了"这件事必须在回放里看得见。

### 4.7 Agent 4 输出

```python
class Issue(TypedDict):
    checker: str
    level: Literal["fail", "warn", "info"]
    finding_ids: list[str]
    detail: str
    location: str | None               # 字段键 / chunk_id / trail entry id

class VerificationReport(TypedDict):
    checks: list[Issue]
    verdict: Literal["pass", "warn", "fail"]
    credibility: dict                  # 全部可复算，口径见 agent-audit spec
    score: float | None                # 展示用，MUST NOT 参与判定或重跑
```

### 4.8 输入与检索

```python
class SourceFile(TypedDict):
    file_id: str
    filename: str
    mime: str
    path: str                          # 本地路径或对象存储 key
    sha256: str                        # docs 复用判定与去重

class Chunk(TypedDict):
    chunk_id: str
    doc_id: str                        # 知识库文档 ID（不是业务材料 file_id）
    title: str
    text: str
    score: float
    source_type: Literal["kb", "web"]
```

### 4.9 主状态与临时通道

```python
class EditState(TypedDict, total=False):
    run_id: str
    files: list[SourceFile]
    business_type: str | None

    docs: list[ParsedDoc]                                  # 覆盖，parse 产出
    fields: dict[str, FieldValue]                          # 覆盖
    extra_fields: dict[str, FieldValue]                    # 覆盖，fields.yaml 未定义的
    _candidates: list[dict]                                # 【临时通道】extract 写、normalize 清
    findings: Annotated[list[Finding], operator.add]        # reducer
    legal: LegalOpinion | None                             # 覆盖
    retrieved: list[Chunk]                                 # 覆盖

    trail: Annotated[list[TrailEntry], operator.add]        # 追加
    stages: Annotated[list[StageReport], operator.add]      # 追加

    verification: VerificationReport | None                 # 覆盖
    gate: dict | None
    export: dict | None

    recheck: bool
    recheck_count: int
    repair_count: int
    requested_stages: list[str]
```

**只有 `findings` / `trail` / `stages` 三个键有 reducer。** `fields` / `legal` 等一律覆盖 ——
随手加 reducer 会在 `reset` 循环里叠加。

`_candidates` 三条铁律：① `extract` 只写、`normalize` 必须 `Overwrite([])` 清空（否则被
checkpointer 长期保存）；② 前端预览可读它，但**不得**当 `fields` 用；③ 它**不进契约**，
任何 Agent MUST NOT 依赖它做判定。

## 5. 冻结约束与十处裁决

### 5.1 冻结后不许改的三条

1. **子结构只增不改**：新增字段必须可选（`NotRequired`），否则 fixture 与三个 Agent 同时返工
2. **改契约需三人同时同意**，改完重跑 `pytest tests/test_contracts.py` 并更新对应 fixture
3. **`【语义】` 注释与字段同等重要**：改语义等同改契约（`value` 大小写、`span` 粒度、
   `confirmed`、`missing` 占位都属语义）

### 5.2 十处设计稿不一致的最终裁决（code review 依据）

| # | 不一致 | 裁决 |
|---|---|---|
| 1 | `agent-normalize/design.md` 让 `parse()` 返回 `parse_errors`，`EditState` 无此键 | **不新增 state 键**：错误写 `ParsedDoc.errors` + `StageReport(partial/failed, reason=…)` |
| 2 | 旧边表有 `repair → agent2_again`，但无此节点 | **不新增节点**：`repair` 用条件边直接回 `agent2` / `agent3` / `hitl` |
| 3 | `agent-verify` 引用 `Finding.confidence` / `needs_review`，契约没有 | 加**可选**字段（§4.4），需三人补签一次 |
| 4 | `agent-audit` 伪码读 `state["retrieved_by_finding"]`，该键不存在 | Agent 4 内部由 `findings[].citation` **现算**；派生数据不入 state |
| 5 | `escalate_to_human` 触发条件两处计数不一致（5 vs 6） | 编排层不判定，只读 `legal.escalate_to_human`；C 必须给唯一清单（**仍待确认**） |
| 6 | 共享层要求纯函数，契约要求抽取留痕 | `extract()` 返回 `trail_entries`，节点用 `record_many()` 写回 |
| 7 | 检查器要求只读，但 `conflict_check` 会写 `StageReport` | **检查器只返回 `Issue`，不许写 state**；`agent4` 节点统一聚合后写一条阶段记录 |
| 8 | 三分类有 `missing`，但只遍历候选 → 该枚举永远不出现 | `required` 且无候选 → 占位 `status="missing"` + `notes=["not_in_source"]` + `op="pass"` |
| 9 | `max_length` 挂字段顶层、`stage` 里没写 → 截断无人认领 | 形式约束（`max_length` / `charset` / `precision` / `thousands` / `date_order`）归 `stage.normalize`（A）；`required` / `positive` 归 `stage.validate`（B），A 只**读** `required` 用于补占位 |
| 10 | `business_type` 有两个写入方（`ingest` 与 Agent 1） | `ingest` 只透传，**`normalize` 是唯一写入者**；Agent 3 在 `raw` 模式推断的类型只写 `legal.coverage` |

> 判定方法固定为一句：**"违反了是系统没读懂，还是业务不允许？"** 前者归 A（`normalize`），
> 后者归 B（`validate`）。同一约束不得两人各实现一遍。

## 6. 共享层签名（纯函数，冻结）

```python
# file: app/parsing/parse.py
def parse(files: list[SourceFile]) -> tuple[list[ParsedDoc], list[dict], int]:
    """返回 (docs, trail_entries, model_calls)。0 次模型调用。失败写 errors，不抛异常。"""

# file: app/parsing/extract.py
@dataclass(frozen=True)
class ExtractResult:
    candidates: list[dict]          # 不写 fields；进 _candidates
    trail_entries: list[dict]       # 由节点 record_many 写回
    model_calls: int
    failed_batches: list[str]

def extract(docs: list[ParsedDoc], field_keys: list[str], *, llm,
            model: str = "gpt-4o", batch_chars: int = 12000) -> ExtractResult: ...

# file: app/parsing/normalize.py
MAX_SPAN_LEN = 200                  # 与 agent-audit 的 provenance_check 共用同一常量
def normalize_ws(text: str) -> str: ...
def locate_span(full_text: str, span: str) -> bool: ...   # 内部只走 normalize_ws
@dataclass(frozen=True)
class NormalizeResult:
    fields: dict[str, FieldValue]
    extra_fields: dict[str, FieldValue]
    business_type: str | None
    findings: list[Finding]
    trail_entries: list[dict]
def build_fields(candidates: list[dict], docs: list[ParsedDoc], *,
                 fields_yaml: dict) -> NormalizeResult: ...
def detect_business_type(docs: list[ParsedDoc]) -> str | None: ...
```

**三条纪律（违反即视为破坏接缝）**

1. 函数签名里**不出现 `state`**：共享层可在无图状态下单测；留痕以 `trail_entries` 返回
2. `normalize_ws` / `MAX_SPAN_LEN` **只在这里定义一次**；A 判定 `extracted`、C 的
   `provenance_check`、B 的一致性比对都必须 import，禁止各写一份
3. `extract` 是**唯一**模型入口：`normalize` 纯代码，`parse` 零模型调用

`normalize_ws` 五步权威顺序：NFKC 全半角 → 剔除零宽字符 → 连字符归一（`U+2010–U+2015`、`U+2212`）
→ 引号归一（弯引号 / `«»` / `「」`）→ 空白折叠。**不做**大小写折叠、去标点、同义词换算 ——
否则 `provenance_check` 验不出"模型改写了原文"。

## 7. 阶段登记与前置校验（`app/stages.py`）

这是**唯一允许声明"我依赖什么"的地方**。任何 Agent 想被独立触发，就必须在这里登记。

```python
@dataclass(frozen=True)
class AgentSpec:
    agent_id: str                     # agent1 .. agent4（共享阶段记 agent1）
    requires_stages: tuple[str, ...]  # 必须先 done 的阶段
    requires_keys: tuple[str, ...]    # 必须非空的 state 键
    produces: tuple[str, ...]         # 会写哪些键（重跑前据此清理）
    standalone: bool                  # 能否单独触发
    cleared_on_rerun: tuple[str, ...] = ()

AGENT_SPECS = {
    "agent1": AgentSpec("agent1", (), ("files",),
                        ("docs", "fields", "extra_fields", "business_type", "findings"),
                        True, ("docs", "fields", "extra_fields")),
    "agent2": AgentSpec("agent2", ("normalize",), ("fields", "business_type"),
                        ("findings", "stages", "trail"), True),
    "agent3": AgentSpec("agent3", ("parse",), ("files",),
                        ("findings", "legal", "retrieved", "stages", "trail"), True),
    "agent4": AgentSpec("agent4", ("merge",), ("findings", "stages"),
                        ("verification", "stages", "trail"), False),
}
# 阶段目标：不是 Agent，但必须能单独触发（agent-normalize 的三档验收依赖它）
STAGE_TARGETS = {
    "parse":     AgentSpec("agent1", (), ("files",), ("docs",), True),
    "extract":   AgentSpec("agent1", ("parse",), ("docs",), ("_candidates",), True),
    "normalize": AgentSpec("agent1", ("parse", "extract"), ("_candidates",),
                           ("fields", "extra_fields", "business_type", "findings"),
                           True, ("fields", "extra_fields", "business_type")),
}
ENRICHED_CHAIN = ("parse", "extract", "normalize")
RAW_BACKFILL = ("parse",)
```

**三条落地细节**

1. **拒绝 ≠ 空结果**：拒绝时返回 `{"refused": true, "missing": [...]}`，图内路径还要写一条
   `StageReport(failed, reason=…)`；**绝不返回 `findings=[]`**
2. **阶段报告只追加**：重跑后同名多条，`latest_stage()` 取最后一条
3. **`normalize` 未 done 时 Agent 2 必须拒绝**：契约允许"`docs` 缺失时只按字段判定"，
   **不允许**在 `fields` 缺失时输出零 findings

## 8. 留痕（`app/trail.py`）

```python
def record(state: dict, *, agent: str, stage: str, op: str,
           before: str | None = None, after: str | None = None,
           ref: str | None = None, model: str | None = None,
           prompt_hash: str | None = None, detail: dict | None = None) -> dict:
    """返回 {"trail": [entry]}，由 reducer 追加。id 在 agent 内自增。"""

def record_many(state: dict, *, agent: str, stage: str,
                entries: list[dict]) -> dict:
    """共享层回执（ExtractResult.trail_entries / NormalizeResult.trail_entries）专用。"""
```

**op 口径（写进 prompt 与 code review）**

| op | 什么时候写 | 常见错误 |
|---|---|---|
| `read` | 读入原文片段 | — |
| `llm_call` | 每次模型调用，必带 `model` + `prompt_hash` | 漏记 → 无法复现，Agent 4 报 `fail` |
| `transform` | 代码转换（规范化、映射、用户改值） | 用 `emit` 代替 → 分不清是模型产出还是代码转换 |
| `emit` | 产出一个字段 / Finding / claim | 无 `after` 或 `ref` |
| `pass` | 判定可接受 / 合理跳过（`detail.reason` 必填） | 记成 `drop` → 被 Agent 4 判越界 |
| `summarize` / `rewrite` / `drop` | **越界信号**：只有真的改写了事实才会出现 | 把"按范围跳过"记成 `drop` |

## 9. 确定性节点不变量

| 节点 | 必须保证 | 禁止 |
|---|---|---|
| `ingest` | `run_id` / `file_id` / `sha256` 一次生成 | 写 `business_type`（只透传入参） |
| `parse` | 失败写 `ParsedDoc.errors` + 阶段 `partial/failed`；`sha256` 未变则复用 `docs` | 抛异常中断全图；返回空 `full_text` 冒充成功 |
| `extract` | 只写 `_candidates` + `trail` | 写 `fields`；在共享层内 `record(state, …)` |
| `normalize` | 三分类 + `missing` 占位 + `Overwrite([])` 清 `_candidates` | 做任何 LLM 调用（纯代码） |
| `reset` | `findings` 用 `Overwrite([])`；其余循环键普通赋值置空 | 清 `stages` / `trail`；对 LastValue 键用 `Overwrite` |
| `merge` | 去重键 `(source, rule_id, sorted(field_keys), evidence)`；排序 `severity→blocking→id` | 重新编号；丢弃不同 source 的同类结论 |
| `gate` | 六条判定**全量收集**、固定顺序、`blocked` 为默认 | 短路返回第一条；读 `score` 做判定；失败边指回 `hitl` |
| `export` | 仅 `pass` 产出；写不可变版本；`blocked` 时双保险拒绝 | 在 `gate` 里直接导出；允许调用方指定版本号 |
| `repair` | 只清被重跑分支；保留 `verification` 作反馈 | 传分数当反馈；重跑输入类失败 |
| `hitl` | `interrupt()` 前无副作用；resume 幂等 | 在暂停前写库或调模型 |

## 10. 主图（`app/graph.py`）

```python
g.add_edge(START, "ingest")
for a, b in [("ingest", "parse"), ("parse", "extract"),
             ("extract", "normalize"), ("normalize", "reset")]:
    g.add_edge(a, b)
g.add_edge("reset", "agent2")                 # 并行：同一超级步
g.add_edge("reset", "agent3")
g.add_edge(["agent2", "agent3"], "merge")     # 等待式汇合，只等本轮被调度的分支
g.add_edge("merge", "agent4")
g.add_conditional_edges("agent4", route_after_verifier, {"repair": "repair", "hitl": "hitl"})
g.add_conditional_edges("repair", route_after_repair,
                        {"agent2": "agent2", "agent3": "agent3", "hitl": "hitl"})
g.add_conditional_edges("hitl", route_after_hitl, {"reset": "reset", "gate": "gate"})
g.add_conditional_edges("gate", route_after_gate, {"export": "export", "end": END})
g.add_edge("export", END)
```

**五个必须解释清楚的设计点**

1. **并行用普通边，不用 `Send`**：`Send` 会要求每个分支写同一个键（如 `docs`），而 `docs` 没有
   reducer；加 reducer 就违反契约。唯一的动态扇出（多文件解析）收敛在 `parse` 节点内部
   （`asyncio.gather`）。**把并发关在节点内部，是唯一不破坏契约的做法。**
2. **汇合边是"等待式"**：只等本超级步被调度到的分支，所以 `repair` 只重跑 `agent2` 时
   `merge` 不会死等 `agent3`。若升级后行为变了，退化方案是加 `pending_branches` 屏障，
   **不要**给 `docs` / `legal` 加 reducer。
3. **`reset` 首次运行也要跑**：它保证"本轮起点干净"而不是清历史；`Overwrite([])` 在空
   `findings` 上幂等。这样"首次"与"重跑"走同一条代码路径。
4. **`agent4` 之后不直接进 `gate`**：可修复失败走 `repair`（预算 1 次），不可修复失败走 `hitl`
   让用户补件。直接进 `gate` 会丢掉"修一次"的机会；无限重跑会让演示时间不可控。
5. **`gate` 失败边指向 `END`**：契约要求"闸门失败不回核对台"，否则用户会在"改又改不对、
   系统反复弹核对台"的循环里出不来。拦截原因一次全返回，用户改完重新发起一次运行。

## 11. 人工核对（`app/nodes/hitl.py`）

**pause 契约**：`hitl` 调 `interrupt()`，payload 必须自包含（前端只拿得到它）：

```python
{
  "run_id": ..., "business_type": ...,
  "fields": [{"key", "value", "status", "confirmed", "source", "notes"}],   # 按 key 排序
  "findings": [{"id", "source", "severity", "blocking", "message", "evidence"}],
  "legal": {"input_mode", "summary", "escalate_to_human", "coverage"},
  "verification": {"verdict", "checks"},
  "stages": [{"stage", "status", "produced", "reason"}],
}
```

**resume 契约**：`Command(resume={"edits": [{"key", "value"}], "recheck": true})`
→ 合并进 `fields`（`confirmed=true`、`edited_by_user=true`、`normalized_from` 保留旧值、
写 `op="transform"` 留痕）→ `recheck_count += 1`。

**三条硬约束（违反会导致重复扣费或重复写库）**

1. `interrupt()` 之前**不得**有模型调用、写库、发通知
2. resume 必须**幂等**：同一 payload 提交两次只生效一次
3. resume 后**不得**重跑 `parse` / `extract`（依赖 checkpointer + 已 done 的阶段）

## 12. 受控重跑（`app/nodes/repair.py`）

| 触发条件 | 是否重跑 | 实现位置 |
|---|---|---|
| `verdict == "fail"` 且有 `level="fail"` 的**可修复**检查项 | 是（`repair_count < 1`） | `route_after_verifier` |
| `verification.score` 偏低但检查全过 | **否** | 路由根本不读 `score` |
| 失败属输入类（原文缺数据、文件不可解析、权限不足） | **否**，直接 `hitl` | `UNREPAIRABLE` |
| `repair_count >= 1` 或总重跑 ≥ 3 | **否**，降级人工复核 | `route_after_repair` |

```python
FIXABLE_BY = {"evidence_locatable": {"agent2", "agent3"},
              "span_locatable": {"agent2", "agent3"},
              "citation_present": {"agent3"},
              "field_key_resolvable": {"agent2"}}
UNREPAIRABLE = {"input_invalid", "source_missing", "coverage_unavailable"}
```

**三条落地细节**

1. **只清被重跑分支的结论**：全清会丢掉另一条分支的结果，不清会留下旧的失败结论
2. **`verification` 留着当反馈**，不新增 `repair_feedback` 状态键（少一次契约变更）
3. **反馈必须含定位与期望**（`location` + `detail` + `expect`），只传分数等于让 Agent 盲猜

## 13. 独立触发（`app/standalone.py`）

### 13.1 补跑矩阵（唯一权威表）

| 目标 | 声明 | 自动补跑 | `input_mode` | 前置不足时 |
|---|---|---|---|---|
| `parse`（只解析） | `stages=parse` | — | — | 无 `files` → `409 REFUSED` |
| `extract`（跑到抽取） | `stages=extract` | `parse` | — | 无 `files` → `409 REFUSED`；**不写 `fields`** |
| `normalize`（只抽字段） | `stages=normalize` | `parse → extract` | — | 无 `files` → `409 REFUSED` |
| `agent2`（只跑要件校验） | `stages=agent2` | `parse → extract → normalize` | — | `fields` / `business_type` 缺失且无法补 → `409 REFUSED` |
| `agent3`（enriched） | `stages=agent3` | `parse → extract → normalize` | `enriched` | 同上 |
| `agent3`（raw：直接扫原文） | `stages=agent3, input_mode=raw` | 仅 `parse` | `raw` | 无 `files` → `409 REFUSED` |
| `agent4` | — | **不允许** | — | `403 NOT_STANDALONE` |

```python
BACKFILL = {
    "agent1":   {"enriched": ()},
    "parse":    {"enriched": ()},
    "extract":  {"enriched": ("parse",)},
    "normalize":{"enriched": ("parse", "extract")},
    "agent2":   {"enriched": ENRICHED_CHAIN},
    "agent3":   {"enriched": ENRICHED_CHAIN, "raw": RAW_BACKFILL},
}

def plan_standalone(state, target, mode="enriched") -> tuple[list[str], dict | None]:
    """返回 (待执行阶段序列, refusal)。序列已去掉已 done 的阶段。"""

def clear_previous_outputs(state, target) -> dict:
    """清掉该目标上一轮产出：只清它负责的那一类结论；stages / trail 不清。"""
```

### 13.2 三条设计理由

1. **独立触发编译线性图**，不是在完整图上"跳着走"：条件边依赖的键在独立触发时大多不存在，
   硬走全图会进一堆 `skipped`，回放里全是噪声
2. **必须清上一轮产出**：不清则 reducer 会叠加，重跑一次就出现两份相同结论
3. **未登记目标必须 409**，不能静默跑全链：否则"只跑解析"实际跑了全流程，扣费与耗时都对不上

## 14. 测试与验收

| 文件 | 守住哪条底线 |
|---|---|
| `tests/test_contracts.py` | 每个结构必填键与枚举值；`field_keys` 是 `[]` 不是 `None` |
| `tests/test_stages.py` | `done+0` 与 `skipped+0` 必须可区分；重跑取最后一条 |
| `tests/test_trail.py` | 越界 op 可被检出；ID 跨 Agent 不冲突 |
| `tests/test_parsing.py` | 两条调用路径 `blocks` 逐块一致；`normalize_ws` 覆盖全半角/`U+2011`/弯引号 |
| `tests/test_gate.py` | 六条判定各自阻断；不短路；分数不参与 |
| `tests/test_repair.py` | 分数不触发；输入类失败不重跑；预算耗尽转人工 |
| `tests/test_graph_flow.py` | 全图跑到 `interrupt` 且 payload 结构正确 |
| `tests/test_resume.py` | resume 后 `parse` / `extract` 未重跑 |
| `tests/test_standalone.py` | 独立触发补前置、`input_mode` 正确、上一轮结论被清 |

**fixtures 四对（D1 冻结即生效）**

| fixture | 上游 → 下游 | 谁出 |
|---|---|---|
| `fixtures/seam_a_to_b/` | A 的 `fields` → B 的校验 | A |
| `fixtures/seam_a_to_c/` | A 的 `docs` → C 的检索输入 | A |
| `fixtures/seam_ac_to_d/` | 全体产出 → Agent 4 检查 | C（A 出 `provenance_check` 断言） |
| `fixtures/seam_bd_to_gate/` | `findings` + `verification` → `gate` | Orchestrator |

**每日必绿**：`test_stages.py`、`test_gate.py`、`test_graph_flow.py` —— 覆盖"没检查≠没问题"、
"不确定即阻断"、"全图能跑"三条底线。

## 15. 风险与未决项

| 风险 | 触发概率 | 影响 | 缓解 |
|---|---|---|---|
| 某人在自己 Agent 里另写一份解析 | 高 | 同一文档两次扫描结论不同 | `test_parsing.py` + code review checklist |
| 为"通过演示"把 `gate` 改宽松 | 中 | 合规风险，产品价值归零 | 判定顺序写死 + 5 个单测锁住 |
| 分数被偷偷接入重跑 | 中 | 不可复算的重跑，成本失控 | 路由代码里根本不读 `score` |
| `stages` 无限增长 | 低 | checkpoint 变大 | 只存摘要（无原文），M3 起归档 `run_events` |
| SQLite 并发写冲突 | 中 | 演示偶发 `database is locked` | 进程内锁 + 演示机不跑并行运行 |
| `interrupt` 前写了副作用 | 中 | 恢复时重复扣费/重复写库 | §11 三条硬约束 + review 第一条 |

**仍待他人拍板**：`MAX_SPAN_LEN=200` 是否够用（A+C）、`required` 由 A 读取是否算越界（A+B）、
`business_type` 强指示词表是否需业务确认（业务+A）、`escalate_to_human` 唯一清单（C）。
结论写回本文件与《实施设计》，不留 PR 评论。