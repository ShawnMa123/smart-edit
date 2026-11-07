# Design: POC 骨架与契约冻结

> 本文件是**唯一契约真相源**，也是全部设计的唯一来源 —— 项目不另设设计文档。
> 实现时 `app/state.py` 必须与本文件逐字段一致；两者不一致以本文件为准。

## 目录结构

```text
app/
  state.py                 # 契约，D1 冻结
  graph.py                 # 主图

  parsing/                 # 共享层：三个 agent 都能独立调
    parse.py               #   自由文本 PDF / 邮件 / 纯文本 -> ParsedDoc
    extract.py             #   ParsedDoc -> 候选字段（唯一 LLM 抽取入口）
    normalize.py           #   候选 -> FieldValue（纯代码）

  trail.py                 # 操作日志（全局约束的落地载体）
  stages.py                # StageReport 读写helper

  nodes/
    ingest.py  reset.py  merge.py  gate.py  export.py  hitl.py
    repair.py              # 受控重跑调度

  agents/
    normalize/             # A · Agent 1
    verify/                # B · Agent 2
    regulatory/            # C · Agent 3

  verifier/
    registry.py            # C · Agent 4 框架
    checkers/              # C 框架 / A 提供两个

  api/main.py
  storage/doc_versions.py
```

### 为什么 `parsing/` 是共享层

`agent1` 不是这些步骤的私有者。独立触发 Agent 3 时（用户直接扫原始文档、不等 Agent 1），
同样需要 `parse`；支持"只跑要件校验"时也需要 `extract`。

若每个 agent 各自实现一份解析，同一份 PDF 会切出不同段落、`evidence` 定位到不同位置，
演示时会出现"同一文档两次扫描结论不同"且无法解释。

**因此 `parse` / `extract` / `normalize` 三件事只有一份实现，任何 agent 通过声明前置阶段来组合它们。**

---

## 契约

### 1. 基础结构

```python
# ---------- 解析产物 ----------

class ParsedBlock(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None          # [x0, y0, x1, y1]；纯文本为 None
    text: str                          # 原文，未做任何改写
    kind: Literal["paragraph", "table_cell", "header", "footer"]

class ParsedDoc(TypedDict):
    file_id: str
    filename: str
    mime: str
    form: Literal["pdf_text", "pdf_form", "email", "plain_text"]
    blocks: list[ParsedBlock]
    full_text: str                     # blocks 按序拼接，Agent 3 直接消费
    errors: list[str]                  # 解析失败原因；非空时该文件不参与后续


# ---------- 出处 ----------

class Source(TypedDict):
    file_id: str
    page: int | None
    bbox: list[float] | None
    span: str                          # 【语义】最小可定位片段，不含"申请人："之类 label
    form_label: str | None             # 表单栏目名；自由文本恒为 None（POC 不实现表单路径）


# ---------- 字段值 ----------

class FieldValue(TypedDict):
    key: str                           # 来自 fields.yaml
    value: str | None                  # 【语义】规范化后的值，大小写与拼写照原文
    status: Literal["extracted", "inferred", "missing"]
    confirmed: bool                     # 用户是否已在核对台确认
    edited_by_user: bool               # 用户是否手工改过值
    source: Source | None
    normalized_from: str | None        # 规范化前的原值，原样保留
    label: str | None                  # 原文中该字段的原始称呼
    doc_type: str | None               # invoice / contract / bl / application_form …
    notes: list[str]                   # 歧义、截断等说明，如 "date_ambiguous"


# ---------- 审查结论 ----------

class Finding(TypedDict):
    id: str                            # 命名空间见下：N-001 / B-001 / R-001
    source: Literal["normalization", "business", "regulatory"]
    kind: Literal[
        "missing",          # 该有的单据/字段确实没交
        "not_found",        # 交了但没抽出来 —— 处理方式与 missing 相反
        "invalid_value",    # 非法值 / 非法字符 / 超长 / 格式不符
        "inconsistent",     # 值之间矛盾
        "policy_violation", # 违反银行内部业务参数
        "regulatory_risk",  # 法规/惯例/政策风险
        "trail_violation",  # 操作日志显示越界改写
    ]
    rule_id: str
    severity: Literal["critical", "warn", "info"]
    blocking: bool
    resolved: bool
    resolution: str | None
    field_keys: list[str]              # 无关联字段时为空列表，不是 None
    message: str
    evidence: str | None               # 必须是原文片段或字段值，不得为空泛描述
    citation: str | None               # chunk_id，仅 regulatory
    suggestion: str | None


# ---------- Agent 3 输出 ----------

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
    input_mode: Literal["enriched", "raw"]   # 见下，决定下游能做什么
    applicable_rules: list[ApplicableRule]
    claims: list[Claim]
    coverage: dict                     # {jurisdictions, standards, unavailable,
                                       #  business_type_uncertain, notes}
    escalate_to_human: bool
    summary: str


# ---------- 阶段记录（"没问题" vs "没检查"） ----------

class StageReport(TypedDict):
    stage: str                         # "parse" / "agent2.check_rules" …
    agent: Literal["agent1", "agent2", "agent3", "agent4"]
    status: Literal["done", "skipped", "partial", "failed"]
    reason: str | None                 # skipped/failed/partial 必填
    produced: int                      # 本次产出的条目数
    model_calls: int

# 【语义】produced=0 且 status="done"  = 检查过，没问题
#        produced=0 且 status!="done"  = 没检查


# ---------- 操作日志 ----------

class TrailEntry(TypedDict):
    id: str                            # "agent1.extract#003"，agent 内自增，避免并行冲突
    agent: Literal["agent1", "agent2", "agent3", "agent4"]
    stage: str
    op: Literal[
        "read",        # 读取输入的原文片段
        "llm_call",    # 模型调用
        "transform",   # 代码转换（规范化/映射）
        "emit",        # 产出一个字段或 finding
        "pass",        # 判定为可接受，放行
        # 以下三种是【越界操作】：出现即说明 agent 改动了事实
        "summarize", "rewrite", "drop",
    ]
    before: str | None                 # 原文片段
    after: str | None                  # 产出值
    ref: str | None                    # 来源 "file_id/page/span" 或上一条 entry 的 id
    model: str | None
    prompt_hash: str | None
    detail: dict


# ---------- Agent 4 输出 ----------

class Issue(TypedDict):
    checker: str
    level: Literal["fail", "warn", "info"]
    finding_ids: list[str]
    detail: str
    location: str | None               # 字段键 / chunk_id / trail entry id

class VerificationReport(TypedDict):
    checks: list[Issue]
    verdict: Literal["pass", "warn", "fail"]
    credibility: dict                  # 全部可复算，见 Agent 4 spec
    score: float | None                # 展示用，MUST NOT 参与判定
```

### 2. `EditState`

```python
class EditState(TypedDict, total=False):
    run_id: str
    files: list[SourceFile]
    business_type: str | None

    docs: list[ParsedDoc]                                   # 覆盖，parse 产出
    fields: dict[str, FieldValue]                           # 覆盖
    extra_fields: dict[str, FieldValue]                     # 覆盖，fields.yaml 未定义的
    findings: Annotated[list[Finding], operator.add]        # 仅此键有 reducer
    legal: LegalOpinion | None                              # 覆盖
    retrieved: list[Chunk]                                  # 覆盖

    trail: Annotated[list[TrailEntry], operator.add]        # 追加
    stages: Annotated[list[StageReport], operator.add]      # 追加

    verification: VerificationReport | None                 # 覆盖
    gate: dict | None                                       # 覆盖
    export: dict | None                                     # 覆盖

    recheck_count: int                                      # 用户改字段触发的重跑
    repair_count: int                                       # Agent 4 触发的重跑
    recheck: bool
    requested_stages: list[str]                             # 独立触发时声明要跑到哪
```

**只有 `findings` / `trail` / `stages` 三个键有 reducer。** 前两个基于 append 语义安全；
`fields` / `legal` 等一律覆盖 —— 随手加 reducer 会在 `reset` 循环里叠加。

### 3. 冻结后不许改的三条

1. 子结构只增不改：新增字段必须可选
2. 修改契约需三人同时同意，改完重跑 `pytest tests/contracts`
3. 语义注释（`【语义】`）与字段同等重要，改语义等同改契约

---

## 三个跨 Agent 约定

### A. Finding 的 ID 命名空间

| Agent | 前缀 | 例 |
|---|---|---|
| Agent 1 normalization | `N-` | `N-001` |
| Agent 2 business | `B-` | `B-001` |
| Agent 3 regulatory | `R-` | `R-001` |

各 agent 在**自己的命名空间内**自增，`merge` **不重新编号**，只排序去重。
去重键为 `(source, rule_id, tuple(field_keys), evidence)`。

> 为什么不在 merge 里统一编号：并行分支同时写入时，任何全局计数器都要加锁；
> 且 `merge` 之前的 finding 没有 id 会让上游无法在日志里引用它。

### B. `input_mode` 决定下游能做什么

| input_mode | 含义 | 下游约束 |
|---|---|---|
| `enriched` | 跑过 `parse → extract → normalize`，有字段表 | 可做 conflict_check |
| `raw` | 只有 `parse`，直接扫全文 | MUST NOT 做 conflict_check（agent2 没跑）；`field_keys` 必须为空 |

### C. 操作日志（全局约束）

**任何 agent 对原文的自由操作（抽取、转换、概括、丢弃）都必须写 `TrailEntry`。**
这是"只改形式不改事实"唯一可执行的落地方式 —— 否则该约束只是口号。

`summarize` / `rewrite` / `drop` 三种 op 是**越界信号**：一旦出现，Agent 4 必须报 `fail`。
正常的丢弃（如"输入含 50 页，只抽了与保函相关的 6 页"）应记为 `op="pass"` 并在 `detail` 说明理由。

写入约定：

```python
from app.trail import record

record(state, agent="agent1", stage="extract", op="llm_call",
       before=None, after=None, model="gpt-4o", prompt_hash="a1b2",
       detail={"candidates": 14})
```

`record` 追加到 `state["trail"]`，`id` 按 `f"{agent}.{stage}#{n:03d}"` 生成，`n` 为该 agent 内计数。

---

## 主图

```python
g = StateGraph(EditState)
for name, fn in [("ingest", ingest), ("parse", parse_node),
                 ("extract", extract_node), ("normalize", normalize_node),
                 ("reset", reset_checks), ("agent2", verify_graph),
                 ("agent3", regulatory_graph), ("merge", merge),
                 ("agent4", verifier), ("hitl", hitl),
                 ("repair", repair_dispatch), ("gate", gate),
                 ("export", export)]:
    g.add_node(name, fn)

g.add_edge(START, "ingest")
g.add_edge("ingest", "parse")
g.add_edge("parse", "extract")
g.add_edge("extract", "normalize")
g.add_edge("normalize", "reset")
g.add_conditional_edges("reset", fanout)          # Send("agent2") + Send("agent3")
g.add_edge("agent2", "merge")
g.add_edge("agent3", "merge")
g.add_edge("merge", "agent4")
g.add_conditional_edges("agent4", route_after_verifier)  # -> "repair" | "hitl"
g.add_edge("repair", "agent2_again")              # 重跑受影响的分支
g.add_edge("hitl" ...)
g.add_conditional_edges("hitl", route_after_hitl) # -> "reset" | "gate"
g.add_conditional_edges("gate", route_after_gate) # -> "export" | END
g.add_edge("export", END)
```

## 决策

| 决策 | 备选 | 选择理由 |
|---|---|---|
| `parse`/`extract`/`normalize` 提为共享层 | 每个 agent 自带解析 | 独立触发必须有同一套解析，否则同一文档两次扫描结论不同 |
| `StageReport` 显式记录每阶段状态 | 用"空列表"表示无问题 | 空 findings 与"没跑"在数据结构上必须可区分，否则独立触发会静默返回"无问题" |
| Finding 命名空间前缀 | merge 统一编号 | 并行分支写同一全局计数器要加锁，且 merge 前 finding 无 id |
| 操作日志是基础契约而非可选 | 只在 Verifier 内做 | 是"不改变事实"约束唯一可执行形式；越界操作要能被事后查出 |
| 分数不参与阻断 | 分数驱动重跑 | 主观分数不可复算，现场无法解释为一个数字辩护 |
| `input_mode` 显式 | 靠 `legal is None` 推断 | None 有多种含义（没跑/失败/不适用），显式字段才能让下游正确降级 |
| SQLite checkpointer | InMemorySaver | 演示时服务重启会丢暂停会话 |

## 占位实现约定

三个 subgraph 在 D1 交付时必须返回结构正确、内容固定的假数据，并写 `StageReport(status="done")`。
主图能从 START 一路走到 END（含 interrupt 与 gate），其他人再逐段替换。

## 测试

```text
tests/
  test_contracts.py       # 每个结构必填键与枚举值
  test_graph_flow.py      # 全图跑到 interrupt
  test_resume.py          # resume 后 agent1 不重跑
  test_gate.py            # 三分支
  test_stages.py          # done+空 vs skipped+空 必须可区分
  test_standalone.py      # 独立触发 agent2/agent3 时前置缺失被拒绝
  test_trail.py           # 越界 op 能被检出
```
