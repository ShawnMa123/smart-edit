# Design

## Context

动机见 `proposal.md` — Why；行为契约见 `specs/audit-extraction` 与 `specs/audit-policy`。实现前必须理解的现状：

- `POST /runs` 已把 editor 文本保存为 `pasted.txt`，`app/parsing/parse.py` 将其解析为 `docs.blocks`；文本通道不需要改。
- `app/nodes/extract.py` 只接受 `llm` 回调；`app/llm.py` 当前只实现 `fixture:<path>`，`openai:` 明确未实现。缺省 `llm=None` 时 `extract` 直接 `failed`。
- `app/parsing/normalize.py::build_fields()` 已经负责 provenance、类型、`required` 占位与三分类；确定性提取器只需产出候选，不复制这些规则。
- `app/audit/*` 与 `app/rules/*` 已经是纯确定性引擎；`as_of` 目前不存在，`date.fromisoformat` 只支持固定 literal。
- `app/rules/templates.py` 已把 template field expectations 编译到同一 closed DSL，`app/audit/clauses.py` 已处理 document-level required/controlled clauses。
- `app/config.py` 对 `fields.yaml` 采取“配置事故必须显式失败”的原则；新 profile loader MUST 沿用。

## Goals / Non-Goals

**Goals:**

- 当前 editor 文本 → 可解释的字段（值 + span + 状态）→ 确定性 findings，`model_calls=0`。
- profile/policy/as_of 全部版本化并写入报告，同一输入可重放。
- 无 profile 时保持现有 fixture/LLM 行为，便于回归与 demo。
- 新增能力尽量复用现有 `build_fields`、rule engine、template/clause 机制，不建第二套审计内核。

**Non-Goals:**

- 不实现真实豆包/其他模型 provider；LLM 补提取只保留开关与标记，本 change 默认关闭。
- 不实现语义条款判定或自然语言合规结论。
- 不改变审批 gate 的语义、不新增数据库表、不做独立配置编辑器。
- 不尝试解析任意复杂版式；跨页/跨块仍按现有降级规则处理。

## Decisions

### D1 · 两层配置：`fields.yaml` 管字段，extraction profile 管定位

`fields.yaml` 继续定义 key / label / aliases / type / required / normalize 约束；新增 `app/configs/extraction/<profile>.json` 只描述“如何从文本定位值”：labels、`value_kind`、`search`、`max_chars`、置信度、可选的 LLM fallback。

备选“把所有内容塞进一个 profile JSON”被否决：会与 `fields.yaml`、template、rule bundle 三套已版本化的配置形成第四套字段定义，任何一处改动都可能让三者漂移。profile 只引用 key，loader 负责对账。

### D2 · 值形状用受控 `value_kind`，不接受内联正则

`value_kind` 第一版：`amount` / `date` / `currency` / `integer` / `text` / `clause_text`。每个 kind 对应一个内部、已测试的 tokenizer，复用 `app/parsing/normalize.py` 的金额/日期/币种逻辑。

备选“允许配置 regex”被否决：与现有 rule DSL “no scripts / no user regex”的安全原则冲突，且 Python `re` 无法可靠限制灾难性回溯；新格式应通过增加受测 tokenizer 支持。

### D3 · 确定性提取放在 `extract` 节点内，先于 LLM

执行顺序：

1. 有 profile → `app/parsing/deterministic_extract.py::extract_deterministic(docs, profile, fields_config)`。
2. 输出 candidates 写入 `_candidates`，`StageReport(reason="deterministic profile <id>@<version>", model_calls=0)`。
3. 仅当 profile 明确 `llm_fallback.enabled` 且存在未找到/低置信字段时，才调用现有 `extract()` 补齐；模型候选标记为低置信度。
4. 无 profile → 保持现有 `llm` 路径；`llm=None` 仍按原规则 failed，避免把配置缺失伪装成成功。

确定性路径不继承“no provider = failed”，因为它是系统提取器而非模型；报告中 `source` 字段区分 `deterministic` / `fixture` / `llm`。

### D4 · 候选冲突显式降级

每个字段按 `(same block + exact label) > (same block + alias) > (next block)` 排序；同值多命中只保留一个。不同值且置信度接近时，不选任何一个，产出 `status=unconfirmed` 的候选并在 trail 中记录两个来源。`normalize` 会把 `unconfirmed` 变为 `inferred` / `needs_input`，规则自然不能 pass。

备选“取最高置信度”被否决：两个真实值并存时，猜错比让人确认代价更高；现有归一化规范也要求“无法确定必须降级”。

### D5 · `as_of` 在 API 边界固定，引擎保持纯函数

- `POST /runs/{id}/stages/audit` 接受可选 `as_of`（日期字符串）；缺省取服务器当天，并在 response 中回显。
- `audit_node` / `audit_state` 把 `as_of` 放入 audit context；`engine._resolve_operand` 对 `{kind: relative_date, value: today}` 返回 `context["as_of"]`。
- 引擎不 import `datetime.date.today`；`tests/test_rule_engine.py` 继续断言无时钟依赖。
- 报告写入 `as_of`；同一 `as_of` 重放必须一致。

备选“引擎直接取今天”被否决：会让历史报告不可重放，也让测试跨天失败。

### D6 · 公司策略继续用 rule bundle + template，不新增规则语言

公司规范写进 `app/rules/bundles/company-guarantee.yaml`；客户/交易对手规范继续写 `app/templates/*.yaml`。两者都经过现有 `load_bundle` / `compile_expectations` / `find_conflicts`，冲突与未发布包的语义保持一致。

`relative_date` 是 DSL 的唯一新增操作数，且只允许 `today`；`LITERAL_COMPATIBILITY` 需要把 `date` 字段与 `relative_date` 视为兼容。

### D7 · Template 选择 profile，显式 profile 只能收窄不能放宽

template 增加可选 `extraction_profile`。解析顺序：

1. 请求 `?profile=`（必须是已发布且 `document_types` 匹配）；
2. 否则 template 的 `extraction_profile`；
3. 否则无 profile → 现有路径。

显式 profile 不会跳过 template fields/clauses 或公司 policy packs；它只替换提取配置。未知/未发布/类型不匹配一律拒绝，不静默回退 fixture。

### D8 · 报告同时暴露 extraction 与 policy provenance

`verification` 增加：

```json
{
  "extraction": {
    "source": "deterministic",
    "profile_id": "guarantee-default",
    "version": "1.0.0",
    "content_sha256": "…",
    "fields_found": 7,
    "fields_missing": 1
  },
  "policy": {
    "template_id": "company-guarantee-v1",
    "bundles": {"guarantee-core": "1.0.0", "company-guarantee": "1.0.0"},
    "as_of": "2026-11-19"
  }
}
```

`source` 缺失时不能伪装为 deterministic；fixture 路径明确标 `fixture`。前端只用这些字段展示来源，不重新推断。

### D9 · LLM 语义复核不在本 change 实现

本 change 只预留 `extraction.llm_fallback` 的结构与“模型候选必须 unconfirmed”的规则，不接入 Doubao。语义复核作为后续 change，单独设计 provider、输出 schema 与 advisory gate 约束，避免把隐私/非确定性问题混进 deterministic MVP。

## Risks / Trade-offs

- [标签/日期/金额格式差异导致漏抽] → 每个 `value_kind` 配样例测试；profile 按 document type 版本化；未命中就缺失，不猜。
- [profile 与 fields.yaml 漂移] → loader 启动时对账 key；profile 只引用、不重复字段定义。
- [同字段多值] → 显式 unconfirmed + trail，规则不得 pass；不静默取一个。
- [日期顺序歧义] → 继续使用 `fields.yaml.date_order`；歧义降级，不在提取器里猜。
- [新增 `relative_date` 破坏规则兼容] → 只接受 `today`，其余值加载失败；`LITERAL_COMPATIBILITY` 增加 date 兼容并有单测。
- [确定性提取改变现有 fixture 测试] → 无 profile 时行为不变；fixture 测试显式断言 `source=fixture`。
- [profile 选择放宽策略] → 显式 profile 只替换提取，不跳过 template/公司包；未发布/类型不匹配拒绝。
- [报告体积增加] → 只记录身份、版本、计数；不把全部候选写进 verification。

## Migration Plan

1. 先合入 profile loader + 确定性提取器 + `extract` 节点分支；默认不选 profile，现有行为不变。
2. 增加 `relative_date` 与公司 bundle；未发布包不参与，现有规则结果不变。
3. template 增加 `extraction_profile`；灰度到单个 template，报告同时标注来源。
4. 前端展示 provenance；旧报告没有新字段时显示“legacy”。
5. 回滚：删除 template 的 profile 引用或清空请求 `?profile=` 即回到原路径；无数据库迁移。

## Open Questions

- 金额大写/文字金额（“USD Five Hundred Thousand”）是否进入第一版 `amount` tokenizer？本 change 先只支持数字形式，后续按样例扩展。
- profile 是否需要按组织维度覆盖（org-specific profile）？本 change 只做发布级 profile，组织级覆盖留到配置管理需求明确后。