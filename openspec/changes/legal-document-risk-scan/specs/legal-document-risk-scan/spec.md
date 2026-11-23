# Spec Delta

## Purpose

规定「草稿法规风险扫描」（`scope=document`）的行为：先计划条款再评估、确定性检查不依赖模型、
逐条款用 `/v1/retrieve` 取证据、模型只能在给定证据内归纳、联网补检由用户选择且永不阻断、
覆盖率与闸门必须把「没检查」如实呈现。

## ADDED Requirements

### Requirement: 扫描 MUST 先计划条款，再评估

系统 SHALL 先把草稿投影为 canonical text 并按条款切分，计划单元（元素/一致性/条款/可选 web）
构成覆盖率分母；每个 finding 的草稿锚点 `quote` SHALL 是草稿文本的连续子串；
超过 `MAX_CLAUSES` 时 SHALL 在 `coverage_summary.truncated` 与 `limitations` 中声明。

#### Scenario: 锚点可回跳

- **WHEN** 某条款命中「自动展期」措辞
- **THEN** finding 的 `document_anchors[0].quote` 是草稿子串，`block_index` 指向该段落，`clause_id` 非空

#### Scenario: 截断如实声明

- **WHEN** 草稿切出 20 个条款且 `MAX_CLAUSES=12`
- **THEN** 报告 `completion=partial`，`coverage_summary.truncated=true`，`limitations` 含 `code=truncated`

### Requirement: 确定性检查 MUST 不依赖模型

必需要素（金额、币种、失效日、适用规则、当事人、开立日、管辖、索赔单据）、日期一致性、
高风险措辞与占位符 SHALL 由确定性规则给出；缺失要素 SHALL 是 finding 而非 pass；
日期解析不出 SHALL 是 `needs_input`，MUST NOT 猜测 DMY/MDY。

#### Scenario: 缺金额阻断

- **WHEN** 草稿不含金额
- **THEN** 产生 `Critical`/`hard_block` finding，`basis=rule`，`gate.status=blocked`

#### Scenario: 日期无法解析不算通过

- **WHEN** 草稿有「失效日期」标签但其后 120 字内没有可识别日期
- **THEN** `LEGAL:consistency:dates_ordered` 为 `needs_input`，`missing_facts` 含 `expiry_date`

### Requirement: 法规腿 MUST 逐条款检索，MUST NOT 用 `/v1/chat`

`scope=document` 的法规腿 SHALL 对每个条款调用一次 `/v1/retrieve`（带 `jurisdictions` / `as_of` 过滤），
MUST NOT 用 `/v1/chat` 做逐条款扫描；服务报告的 `zero:*`、`uncovered:*`、`low_confidence`、`superseded`
SHALL 映射为 `unable_to_assess` 并记录原因与命中数。

#### Scenario: 零命中不硬凑

- **WHEN** `/v1/retrieve` 对某条款返回 0 个 chunk
- **THEN** 该条款 check 为 `unable_to_assess`（`zero:*`），不产生 finding，且该条款进入「未覆盖」集合

#### Scenario: 法域未覆盖

- **WHEN** 服务返回 `field_matches.requested_uncovered.jurisdictions=[\"US\"]`
- **THEN** 该条款 check 的 `reason_codes` 含 `uncovered:US`，状态下为 `unable_to_assess`

### Requirement: 模型 MUST 只引用给定证据，且不得提升严重度

composer SHALL 收到 `rules` 与 `evidence`（含 `id`）并返回 JSON；系统 SHALL 丢弃未知 `rule_id`
与未知 `evidence_ids`，无有效引用时 SHALL 置 `support_level=insufficient`，
`severity` SHALL 不超过 `Warning`，`gate_type` SHALL 不超过 `human_review`，
`quote` 无法在原文定位时 SHALL 不产生草稿锚点。模型不可用时 SHALL 记 `composer_unavailable`，
MUST NOT 产出 `pass`。

#### Scenario: 伪造引用被丢弃

- **WHEN** 模型返回 `evidence_ids=[\"E1\",\"E9\"]` 而只提供了 `E1`
- **THEN** finding 的 `evidence_ids` 只含 `E1`，`severity=Warning`，`gate_type=human_review`

#### Scenario: 无 composer

- **WHEN** 服务运行在 fixture 模式（无 `compose_json`）
- **THEN** 每个有证据的条款 check 为 `unable_to_assess`（`composer_unavailable`），`outcome=unable_to_assess`

### Requirement: 联网补检 MUST 由用户选择，且永不阻断

`web_search` 为 `null` 时 SHALL 使用部署默认（默认 off）；只有用户显式开启且存在未覆盖条款时才 SHALL 调用一次联网；
结果 SHALL 带 `basis=web`、`unverified=true`、`gate_type=human_review`，且 MUST NOT `hard_block`；
无可解析 URL 的结果 SHALL 丢弃。报告 SHALL 记录 `web_requested` / `web_used` / `web_calls`。

#### Scenario: 默认不出网

- **WHEN** 请求未指定 `web_search` 且未开启部署默认
- **THEN** `retrieval.web_requested=false`、`web_calls=0`，不产生 web finding

#### Scenario: 用户开启后只出网一次

- **WHEN** 用户勾选联网且 3 个条款未被语料覆盖
- **THEN** `web_calls=1`，产生一条 `basis=web` / `unverified` 的 `human_review` finding（有可引用 URL 时）

### Requirement: 覆盖率与闸门 MUST 呈现「没检查」

报告 SHALL 输出 `coverage_summary{planned,settled,assessed,assessed_ratio,by_status,clauses,truncated}`
与 `gate{status,reasons,coverage_ratio,policy}`；存在 `failed/unable_to_assess/needs_input` 单元时 SHALL 增加
`unchecked_units` 原因，`assessed_ratio < COVERAGE_RATIO` 时 SHALL 增加 `limited_coverage`；
任一 `hard_block` finding SHALL 使 `gate.status=blocked`；MUST NOT 把未检查呈现为 `no_findings` 或 `clear`。

#### Scenario: 未检查不是通过

- **WHEN** 全部确定性单元通过，但法规腿因未配置而全部 `failed`
- **THEN** `outcome=unable_to_assess`，`gate.reasons` 含 `unchecked_units`，`gate.status!=clear`

#### Scenario: 硬阻断优先

- **WHEN** 同时存在 `hard_block` finding 与低覆盖率
- **THEN** `gate.status=blocked`，`gate.reasons` 同时含 `hard_block_finding` 与 `limited_coverage`

### Requirement: 扫描 run MUST 可轮询、可持久化、可拒绝过期快照

`scope=document` SHALL 返回 202 + `ReviewRun`（`status=queued`，`report_id` 预留），
`GET /legal/runs/{run_id}` SHALL 返回 `stage` 与 `progress`；报告 SHALL 落盘并按 workspace 校验；
`expected_revision` / `expected_content_sha256` / `draft_id` 与当前草稿不一致时 run SHALL `failed` 且 `error=stale_snapshot`。

#### Scenario: 过期快照被拒

- **WHEN** 客户端 pin 了 revision 3，但服务端草稿已是 revision 9
- **THEN** run `status=failed`、`error=stale_snapshot`，不产生报告（`GET /legal/reports/{id}` 为 404）

#### Scenario: 幂等重试

- **WHEN** 两次提交携带相同 `Idempotency-Key`
- **THEN** 第二次返回同一个 `run_id`，且不触发第二次扫描

### Requirement: 扫描 MUST 识别实质性合规红黄线（制裁 / 出口管制 / 规避）

系统 SHALL 在计划中包含 4 个合规单元：`prohibited-transaction`（受控货物 + 受制裁目的地）、
`export-control`（受控货物）、`sanctions`（受制裁目的地）、`evasion`（规避措辞）。
受控货物 + **全面制裁**目的地 SHALL 产生 `Critical`/`hard_block` finding，并 SHALL 在货物与目的地两处给出草稿锚点；
受控货物 + **行业制裁**目的地 SHALL 产生 `Critical`/`human_review`（不 hard_block）；
仅有规避措辞 SHALL 产生 `Warning`/`human_review`。每个 finding MUST 明确声明这是文本红黄线、不是许可/筛查结论。

#### Scenario: 武器出口到受制裁国家

- **WHEN** 草稿同时出现受控货物（武器/导弹/军用无人机等）与全面制裁目的地（如 Iran）
- **THEN** 产生 `Sensitive goods destined for a sanctioned country`
  （`Critical`/`hard_block`，`basis=rule`），`gate.status=blocked`，且 finding 至少有两个草稿锚点

#### Scenario: 行业制裁目的地不硬阻断

- **WHEN** 受控货物与 Russia（行业制裁）同时出现
- **THEN** 产生 `Sensitive goods destined for a restricted country`，`gate_type=human_review`，闸门不因该条 `blocked`

#### Scenario: 规避措辞单独成立

- **WHEN** 草稿只有 “split the payment / via a third country / avoid sanctions”
- **THEN** 产生 `Circumvention wording detected`（`Warning`/`human_review`），且 `sanctions`/`export-control` 单元为 pass

#### Scenario: 普通商业文本不误报

- **WHEN** 草稿是软件许可合同（Singapore 双方、无受控货物、无规避措辞）
- **THEN** `prohibited-transaction` 为 `not_applicable`，其余三个合规单元为 `pass`，无合规 finding

### Requirement: 要素目录 MUST 按文种选择

系统 SHALL 用小型启发式判定文种（`guarantee` / `lc` / `contract` / `unknown`），
保函/信用证 SHALL 使用保函要素（金额、币种、失效日、适用规则、申请人、受益人、开立日、管辖、索赔单据），
其它文种 SHALL 使用合同要素（金额、币种、当事人、管辖），MUST NOT 用保函要素评判合同。

#### Scenario: 合同不报“缺索赔单据”

- **WHEN** 扫描一份 `EXPORT AGREEMENT`
- **THEN** `snapshot.document_type=contract`，`coverage` 中只有
  `LEGAL:element:{amount,currency,parties,jurisdiction}` 四个要素单元

### Requirement: 合规规则 MUST 可由模型补充，但不得升级

composer 的规则目录 SHALL 始终包含 `LEGAL-COMPLIANCE-{PROHIBITED,EXPORT-CONTROL,SANCTIONS,EVASION,BRIBERY,AML}`；
模型引用这些 id 的 finding SHALL 仍受「只引用给定证据、`severity ≤ Warning`、`gate ≤ human_review`」约束。

#### Scenario: 模型也发现制裁风险

- **WHEN** 条款文本含受控货物但词表未命中具体品名
- **THEN** 模型可用 `LEGAL-COMPLIANCE-EXPORT-CONTROL` 产出 `Warning`/`human_review` finding，且不得 `hard_block`