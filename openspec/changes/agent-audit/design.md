# Design: Agent 4 审计（Audit）

> Contract 真相源在 `changes/poc-skeleton/design.md`。
> 接缝约定见 `changes/poc-skeleton/specs/agent-contract/spec.md`。
> 本文件描述检查器框架、判定口径、可信度比率与受控重跑。

## 定位

Agent 4 是**证据链审计者**，不是评分者。

| 做 | 不做 |
|---|---|
| 检查输出的结构、出处、引用、日志是否成立 | 判断业务对错、法规适用对错 |
| 发现"标了 extracted 但原文里找不到"这类硬问题 | 判断字段抽得全不全 |
| 计算可复算的可信度比率 | 输出主观质量分并据此阻断 |
| 判定是否抑制发布、是否需要重跑 | 自己生成或修补内容 |

**分界线**：线上没有真值，所以只能查"证据链是否自洽"。
"抽得对不对"由离线 benchmark 判断 —— 那是有 gold 真值、在开发机上跑的另一件事，
不在运行路径上，也不属于本 Agent。

## 检查器列表

```text
[输入 EditState]
  |
  v
{遍历 CHECKERS 注册表}
  |
  |-- [schema_check           · C] 三个 Agent 输出符合契约
  |-- [trail_check            · C] 日志完整性 + 越界操作检出
  |-- [conflict_check         · C] Agent 2 与 Agent 3 结论互相矛盾
  |-- [coverage_check         · C] Agent 3 声称的覆盖是否有检索证据
  |-- [citation_check         · C] 引用是否被原文支持
  |-- [provenance_check       · A] 标 extracted 的值是否真在原文里
  |-- [finding_anchor_check   · C] Finding 是否指向真实字段/位置
  |
  v
[汇总 issues]
  |
  v
{verdict}
  |
  |-- 任一 fail 或检查器抛错 --> fail · 抑制发布
  |-- 仅有 warn -------------> warn
  +-- 全通过 ----------------> pass
```

**检查器签名统一**：`def check(state: EditState) -> list[Issue]`，只读不写。

### 分工与"自审"的真实情况

`provenance_check` 交给 A，理由**不是**避免自审 —— 三人团队无法避免。诚实的排布是：

| 检查器 | 校验对象 | 作者 | 是否自审 |
|---|---|---|---|
| `schema_check` | 全体 | C | 部分 |
| `trail_check` | 全体 | C | 部分 |
| `conflict_check` | Agent 2 vs Agent 3 | C | **是**（Agent 3 是 C） |
| `coverage_check` | Agent 3 | C | **是** |
| `citation_check` | Agent 3 | C | **是** |
| `finding_anchor_check` | 全体 | C | 部分 |
| `provenance_check` | Agent 1 | A | **是**（Agent 1 是 A） |

每个人至少自审一个检查器。真正的保障来自三处：

1. **检查器全是确定性代码** —— 判据明文可读，B 花 20 分钟能看出有没有放水。
   这比作者是谁重要得多。
2. **离线 gold 样本有真值** —— 检查器说"通过"、gold 说"错了"，矛盾立刻暴露。
3. **A 的检查器接入时不许改判据**（tasks 3.6）。

**`provenance_check` 交给 A 的真正价值**：写这个检查器的人必须先精确回答
"`span` 取多长才算最小片段 / 归一化包含哪些变换 / 跨行跨页怎么处理"。
这三条是 Agent 1 的核心定义，只有写检查器的人会真的想清楚 ——
由 C 代写，A 可以永远含糊。**这是逼定义落地，不是分摊工作量。**

其余 6 个由 C 实现。`finding_anchor_check` 判据机械（字段是否存在、`evidence` 是否为空），
不需要 A 拍板，放 C 这边减少跨人依赖。

## 共享归一化：一个隐藏的硬接缝

```python
# Agent 1 判定
normalize_ws(span) in normalize_ws(parsed_text)   → "extracted"

# Agent 4 校验
normalize_ws(span) not in normalize_ws(full_text) → "fail"
```

**这两处必须调用同一个函数。** 各自实现一份，一旦分叉（比如一边统一了连字符、另一边没有），
Agent 1 标的 `extracted` 会被 Agent 4 全部判 fail，且失败原因极难定位。

因此：`normalize_ws` 属于共享层，签名与实现进契约，任何 Agent 不得私有化。
见 `poc-skeleton` 的 `agent-contract` spec "归一化规则必须共用"。

---

## 检查器实现规范

以下每个检查器给出判据、level 与产出示例。A 与 C 各自照此实现，判据不得走形。

### 1. `schema_check`（C）

| 判据 | level |
|---|---|
| 任一结构缺必填键 | fail |
| 枚举值越界（`status` / `kind` / `severity` / `input_mode`） | fail |
| `Finding.field_keys` 为 `None` | fail |
| `Finding.id` 前缀与 `source` 不匹配 | fail |
| `legal.applicable_rules` 每项缺 `chunk_id` | fail |
| `FieldValue.notes` 为 `None` | warn |

```python
def schema_check(state) -> list[Issue]:
    issues = []
    for f in state.get("findings", []):
        if f.get("field_keys") is None:
            issues.append(issue("schema_check", "fail", [f["id"]], f["id"],
                                "field_keys 必须为 [] 而不是 null"))
        if not _prefix_matches(f):
            issues.append(issue("schema_check", "fail", [f["id"]], f["id"],
                                f"source={f['source']} 但 id 前缀为 {f['id'][:2]}"))
        if f.get("kind") not in KINDS:
            issues.append(issue("schema_check", "fail", [f["id"]], f["id"],
                                f"kind 越界：{f.get('kind')}"))
    ...
```

---

### 2. `trail_check`（C）· 本项目特有

**三个越界 op 只在违反"只改形式不改事实"时才会被写入。出现即说明约束已被打破 —— 不是风险，是事实。**

| 判据 | level |
|---|---|
| 存在 `op` 为 `summarize` / `rewrite` / `drop` 的条目 | **fail** |
| trail 中出现未声明的 `agent` 值 | fail |
| `trail` 为空但 `fields` 非空 | fail |
| `status="extracted"` 的字段在 trail 中找不到对应 `emit` | warn |
| `llm_call` 缺 `prompt_hash` | warn |
| `op="pass"` 的条目缺 `detail.reason` | warn |

**产出示例**

```python
Issue(
    checker="trail_check", level="fail",
    finding_ids=[],
    location="agent1.extract#007",
    detail="检测到 rewrite 操作：before='新加坡那个公司' after='XYZ IMPORTS CO LTD'；"
           "该操作违反'只改形式不改事实'，本结果不得发布",
)
```

**关键实现点**

```python
BANNED = {"summarize", "rewrite", "drop"}

for e in state.get("trail", []):
    if e["op"] in BANNED:
        issues.append(issue("trail_check", "fail", [], e["id"],
                            f"检测到 {e['op']} 操作：before={e['before']!r} "
                            f"after={e['after']!r}；违反'只改形式不改事实'"))
    if e["op"] == "pass" and not (e.get("detail") or {}).get("reason"):
        issues.append(issue("trail_check", "warn", [], e["id"],
                            "op=pass 未说明跳过理由"))

if state.get("fields") and not state.get("trail"):
    issues.append(issue("trail_check", "fail", [], None,
                        "有字段产出但 trail 为空，说明某个 Agent 完全没留痕"))

# emit 与字段的对应靠 detail.field_key
emitted = {(e["agent"], e["detail"].get("field_key"))
           for e in state["trail"] if e["op"] == "emit"}
for key, fv in state.get("fields", {}).items():
    if fv["status"] == "extracted" and ("agent1", key) not in emitted:
        issues.append(issue("trail_check", "warn", [], key,
                            f"字段 {key} 标为 extracted 但无 emit 记录"))
```

**为什么 `pass` 缺理由只是 warn，而 `drop` 是 fail**：跳过本身合法，缺的只是可解释性；
**`drop` 不带理由就是静默丢弃**，属事实性违规。

---

### 3. `conflict_check`（C）

只比可比的结论。`legal.input_mode == "raw"` 时**跳过**，因为 Agent 2 根本没跑。

| 判据 | level |
|---|---|
| Agent 2 判定某字段值非法，Agent 3 的 claim 却以该值为前提 | fail |
| Agent 2 报 `missing` 某事，Agent 3 的 claim 引用它作为既有事实 | fail |
| 同一条规则被两个 Agent 判出相反结论 | warn |

**不比"合规/不合规"标签** —— Agent 3 根本不产出这种标签（其 spec 明确禁止）。
比的是**事实前提**是否自相矛盾。

**产出示例**

```python
Issue(
    checker="conflict_check", level="fail",
    finding_ids=["B-003"],
    location="applicant_name",
    detail="Agent 2 判定 applicant_name 缺失（B-003），"
           "但 Agent 3 的 claim 以该字段有值为前提："
           "'申请人 ABC TRADING 注册于新加坡，适用政策 P-002'",
)
```

**"claim 是否以某字段为前提"如何判定**（启发式，宁可多报）：

```python
def references(claim, field_key, fv):
    if fv["value"] and fv["value"] in claim["text"]:
        return True
    # claim 引用的 chunk 若被某 Finding 的 evidence 覆盖同一片段
    return claim["chunk_id"] in state["retrieved_by_finding"].get(field_key, set())
```

---

### 4. `coverage_check`（C）

**拦的形态："未检索到问题"被读成"没问题"。**

| 判据 | level |
|---|---|
| `coverage.unavailable=true` 但 summary 未声明未覆盖 | fail |
| `coverage.unavailable=false` 但 `retrieved` 为空 | fail |
| `input_mode="raw"` 且 `business_type_uncertain=false` 但无 `business_type` | fail |
| 声称覆盖某法域，但 `retrieved` 中无该法域相关 chunk | warn |
| `escalate_to_human=false` 但存在 `support="insufficient"` 的 risk 类 claim | warn |

```python
MUST_SAY = ["未覆盖", "未能覆盖", "法规建议未覆盖", "超出覆盖范围"]
MUST_NOT_SAY = ["未发现问题", "无明显问题", "未发现异常", "无适用规则", "合规"]

def _declares_unavailable(s: str) -> bool:
    return any(k in s for k in MUST_SAY)

def _falsely_claims_clean(s: str) -> bool:
    return any(k in s for k in MUST_NOT_SAY)
```

**产出示例**

```python
Issue(
    checker="coverage_check", level="fail",
    finding_ids=[],
    location="legal.summary",
    detail="检索结果为空（retrieved=[]）但 summary 写作"
           "'本次分析未发现明显问题'；应在覆盖未达成时明确声明未覆盖",
)
```

> 这张措辞表是**判定的一部分**，改它等于改判据。改之前要三人确认 —— 否则
> Agent 3 换一句同义表述就能绕过检查。

---

### 5. `citation_check`（C）

三级中的前两级，第三级语义蕴含 POC 不做。

| 判据 | level |
|---|---|
| claim 的 `chunk_id` 不在 `retrieved` 中 | fail |
| claim 含金额/日期/国别/规则号，但被引 chunk 原文中没有该实体 | fail |
| `support="insufficient"` 的 claim 带有 `chunk_id` | warn |
| risk 类 claim 全部 `insufficient` | warn |

**实体抽取 —— 一个必须避开的坑**

```python
ENTITY_PATTERNS = {
    "amount":  r"\b\d[\d,]*\.?\d*\b",
    "date":    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    "rule_id": r"\b[PIK]-\d{3}\b|第\s*\d+\s*条",
    "country": r"\b[A-Z]{2}\b",        # ← 单独用会误命中 BY / IN / IT / NO
}
```

`\b[A-Z]{2}\b` 会命中英文里的 "BY"、"IN"、"IT"、"NO" —— 这些**恰好都是 ISO 国家码**，
所以白名单也救不了。**国别实体必须只在 claim 明确带"国别/注册地/法域"语义时抽取，
或改用 `ISO 国家名 + 代码` 双模式并排除停用词。** 否则 `citation_check` 会产生大量假 fail。

**产出示例**

```python
Issue(
    checker="citation_check", level="fail",
    finding_ids=["R-001"],
    location="K-012",
    detail="claim 含实体 {'48', 'P-003'}，但被引 chunk K-012 原文中均未出现："
           "'保函展期须以书面形式通知受益人……'",
)
```

---

### 6. `provenance_check`（A 实现，C 接注册表）

**整个项目最值钱的检查器** —— 把"能跳回原文的才叫 `extracted`"从口号变成运行时拦截。

| 判据 | level |
|---|---|
| `status="extracted"` 但 `source` 为 `None` | fail |
| `status="extracted"` 但 `source.span` 归一化后不在对应文件全文中 | fail |
| `status="extracted"` 但 `source.file_id` 不在 `docs` 中 | fail |
| `len(span) > MAX_SPAN_LEN`（默认 200） | warn |
| `status="inferred"` 但 `source` 非空 | warn |

```python
from app.parsing.normalize import normalize_ws   # 必须与 Agent 1 同一个函数

full_by_file = {d["file_id"]: normalize_ws(d["full_text"]) for d in state["docs"]}

for key, fv in state.get("fields", {}).items():
    if fv["status"] != "extracted":
        continue
    src = fv.get("source")
    if src is None:
        issues.append(issue("provenance_check", "fail", [], key,
                            "status=extracted 但 source 为 null")); continue
    text = full_by_file.get(src["file_id"])
    if text is None:
        issues.append(issue("provenance_check", "fail", [], key,
                            f"source.file_id={src['file_id']} 不在 docs 中")); continue
    if normalize_ws(src["span"]) not in text:
        issues.append(issue("provenance_check", "fail", [], key,
                            f"span 无法在原文定位：{src['span'][:60]!r}")); continue
    if len(src["span"]) > MAX_SPAN_LEN:
        issues.append(issue("provenance_check", "warn", [], key,
                            f"span 长度 {len(src['span'])} 超过 {MAX_SPAN_LEN}，"
                            f"可能是整行而非最小片段"))
```

**`span` 过长为什么是 warn 而非 fail**：子串匹配无法区分"最小片段"与"抓整行蒙混过关"，
长度是唯一可判定的代理指标。这类情况要么改 Agent 1 的 prompt，要么人工抽检。

**已知盲区，必须主动说明**：本检查器只能验"这个片段在原文中出现过"，
验不了"这个值是不是填对了那一栏"。后者只有 gold 样本能给答案。

---

### 7. `finding_anchor_check`（C）

查**问题的锚点**，与 `provenance_check`（值的出处）不同。

| 判据 | level |
|---|---|
| `field_keys` 中的键既不在 `fields` 也不在 `extra_fields` | fail |
| `evidence` 为空字符串或仅含空白 | fail |
| `source="regulatory"` 但 `citation` 为 `None` | warn |
| `source="business"` 但 `citation` 非 `None` | warn |
| `severity="critical"` 但 `suggestion` 为空 | warn |

**为什么锚点丢失是 fail**：核对台按 `field_keys` 定位并高亮字段。
键不存在 → 前端拿不到 → **这条 critical 问题会消失在界面上**，用户不知道有一条被吞了。

**产出示例**

```python
Issue(
    checker="finding_anchor_check", level="fail",
    finding_ids=["B-007"],
    location="guarantee_amout",
    detail="field_keys 中的 'guarantee_amout' 不在 fields 也不在 extra_fields（疑似拼写错误）",
)
```

---

## verdict 与隔离

```python
def verifier(state):
    issues = []
    for fn in CHECKERS:
        try:
            issues += fn(state)
        except Exception as e:
            issues.append(Issue(checker=fn.__name__, level="fail",
                                finding_ids=[], location=None,
                                detail=f"checker raised: {type(e).__name__}: {e}"))

    verdict = ("fail" if any(i["level"] == "fail" for i in issues)
               else "warn" if any(i["level"] == "warn" for i in issues)
               else "pass")

    # 阶段未完成时不得通过
    if verdict == "pass" and any(s["status"] != "done" for s in state["stages"]):
        verdict = "warn"

    return {"verification": {
        "checks": issues, "verdict": verdict,
        "credibility": compute_credibility(state, issues), "score": None,
    }}
```

**单个检查器抛异常 → 记 fail，其余继续。** 不整图失败，也不允许静默跳过 ——
崩溃必须体现为 fail，否则"检查器坏了"会被当成"通过"。

**注意 `verdict == "pass"` 的那段修正**：即使全部检查器通过，只要某个必需阶段没跑完
（`skipped` / `failed` / `partial`），就不能给 pass。这是"没检查 ≠ 没问题"在 Agent 4 的落实。

## 可信度：全部可复算

```python
def compute_credibility(state, issues):
    fields = state.get("fields", {})

    claimed = [k for k, v in fields.items() if v["status"] == "extracted"]
    bad = {i.location for i in issues
           if i.checker == "provenance_check" and i.level == "fail"}
    provenance_coverage = ((len(claimed) - len(bad)) / len(claimed)
                           if claimed else 1.0)

    claims = (state.get("legal") or {}).get("claims", [])
    cited = [c for c in claims if c["chunk_id"]]
    supported = [c for c in cited if c["support"] == "supported"]
    citation_support = len(supported) / len(cited) if cited else 1.0

    inferred = [k for k, v in fields.items() if v["status"] == "inferred"]
    unconfirmed = [k for k in inferred if not fields[k]["confirmed"]]
    inferred_unconfirmed_rate = (len(unconfirmed) / len(fields) if fields else 1.0)

    return {"provenance_coverage": round(provenance_coverage, 4),
            "citation_support": round(citation_support, 4),
            "inferred_unconfirmed_rate": round(inferred_unconfirmed_rate, 4)}
```

三条规则：

1. **分母为 0 时返回 `1.0`，不得返回 `0.0`** —— `0.0` 会被误读为"极差"
2. 三个都是除法，任何人拿到 state 都能复算，必须一致
3. **不做加权合成** —— 综合分会掩盖"引用 1.0 / 出处 0.4"这类关键差异

### score 字段

- **MUST NOT 参与 verdict**、**MUST NOT 触发重跑**
- 仅前端展示，且必须与三个比率同时展示
- 若实现为模型评分，必须标注"模型判断，不可复算"

## 受控重跑（one-shot repair）

### 三条触发条件

```text
1. 只有 level="fail" 触发；warn / info / score 永不触发
2. 失败原因必须可归因：
     schema_check      → 契约问题，人工介入，不重跑
     trail_check       → A 侧，重跑 agent1
     provenance_check  → A 侧，重跑 agent1
     citation_check    → C 侧，重跑 agent3
     coverage_check    → C 侧，重跑 agent3
     conflict_check    → 双方，重跑 agent2 + agent3
3. 失败不是输入问题（PDF 无法解析、原文缺数据 → 不重跑，直接降级）
```

### 为什么不能靠"分数低就重跑"

```text
分低 → 重跑 → 再打分 → 决定是否通过
```

判定者就是被判定对象。结果不是"质量变好了"，而是"重跑恰好蒙到了高分"。
LLM 输出有随机性，三次之内大概率蒙到 —— 这个机制看起来有效，实际是随机的。

### 反馈必须携带失败项

```python
def build_feedback(issues):
    return "\n".join(f"[{i['checker']}] {i['location'] or '-'}: {i['detail']}"
                     for i in issues if i["level"] == "fail")
```

```text
✗ 差：score = 0.6，重跑一次
✓ 好：applicant_name 标了 inferred，但原文第 2 页有 "XYZ IMPORTS CO LTD"，
      请重新定位并给出 span
```

### 预算与路由

```python
def can_repair(state):
    fails = [i for i in state["verification"]["checks"] if i["level"] == "fail"]
    if not fails:                                              return False
    if state.get("repair_count", 0) >= 1:                       return False
    if state.get("recheck_count", 0) + state.get("repair_count", 0) >= 3:
        return False
    if all(i["checker"] == "schema_check" for i in fails):      return False
    if any("无法解析" in i["detail"] for i in fails):            return False
    return True

def route_after_verifier(state):
    return "repair" if can_repair(state) else "hitl"
```

`repair` 之后只回到受影响的分支。**不回 `reset`** —— 那会连 Agent 1 一起重跑，
浪费且会改变字段，使重跑结果与原结果不可比。

## 优化建议的两类消费者

| 消费者 | 内容 | 载体 |
|---|---|---|
| 一线员工 / 审批人 | "该字段无原文依据，请核对后填写"、"本次未覆盖某法域，建议转人工" | `Issue.detail` + `Finding.suggestion`，进核对台 |
| 开发团队 | "extract 对日期字段召回偏低，建议加 few-shot" | `eval/report.md`，**不进运行时** |

开发类建议由离线评测产出，不放进 `VerificationReport` —— 否则运行时会携带大量对员工无意义的文本。

## 失败与降级

| 场景 | 表现 | 降级 |
|---|---|---|
| 单个检查器抛异常 | `Issue(level="fail")` | 其余检查器继续，verdict 为 fail |
| 全部检查器崩溃 | verdict = fail | 抑制发布，转人工 |
| `legal` 为 `None` | 相关检查器跳过 | `StageReport(status="skipped")`，verdict 至少为 warn |
| `stages` 中任一为 `failed` | — | verdict 至少为 warn，MUST NOT 为 pass |
| 重跑预算耗尽 | — | 不重跑，标注"已经重跑 N 次仍未通过" |
| `trail` 为空但 `fields` 非空 | fail | 某个 Agent 完全没留痕，属实现缺陷 |

## 独立触发

**Agent 4 不可单独触发。** 它的校验对象是其他 Agent 的输出，没有这些输出就没有可校验的东西。

请求单独运行 Agent 4 时返回 `{"refused": true, "missing": [...], "agent": "agent4"}`。

## 测试

```text
tests/test_verifier.py
  test_checker_exception_does_not_abort
  test_checker_exception_becomes_fail
  test_credibility_ratios_recomputable
  test_zero_denominator_is_one_not_zero
  test_score_does_not_affect_verdict
  test_stage_failed_cannot_pass

tests/test_schema_check.py
  test_null_field_keys_is_fail
  test_id_prefix_mismatch_is_fail
  test_invalid_enum_is_fail

tests/test_trail_check.py
  test_rewrite_op_causes_fail
  test_drop_op_causes_fail
  test_summarize_op_causes_fail
  test_extracted_without_emit_is_warn
  test_missing_prompt_hash_is_warn
  test_empty_trail_with_fields_is_fail

tests/test_conflict_check.py
  test_skipped_when_input_mode_raw
  test_value_conflict_detected
  test_no_compliance_label_compared

tests/test_coverage_check.py
  test_unavailable_not_declared_is_fail
  test_claims_coverage_but_empty_retrieved_is_fail
  test_clean_summary_with_empty_retrieval_is_fail
  test_raw_mode_without_business_type_is_fail

tests/test_citation_check.py
  test_fabricated_chunk_id_is_fail
  test_entity_not_in_cited_chunk_is_fail
  test_country_entity_not_false_positive   # BY / IN / IT 不应被当国别

tests/test_provenance_check.py
  test_extracted_without_source_is_fail
  test_span_not_in_fulltext_is_fail
  test_span_too_long_is_warn
  test_uses_shared_normalizer

tests/test_finding_anchor_check.py
  test_unknown_field_key_is_fail
  test_empty_evidence_is_fail

tests/test_repair.py
  test_only_fail_triggers_repair
  test_score_never_triggers_repair
  test_feedback_contains_location
  test_input_failure_not_retried
  test_schema_failure_not_retried
  test_repair_targets_responsible_agent
  test_repair_budget_exhausted
```
