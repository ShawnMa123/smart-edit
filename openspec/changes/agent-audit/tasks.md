# Tasks: Agent 4 审计（Audit）

> Owner: C（框架 + 6 个检查器）· A（`provenance_check`）
> 前置：`poc-skeleton` 契约冻结（`VerificationReport` / `Issue` / `TrailEntry`）、
> `repair` 节点、以及共享层 `normalize_ws`

> `provenance_check` 交给 A 的**真实原因**：写这个检查器的人必须先精确回答
> "`span` 取多长才算最小片段 / 归一化包含哪些变换 / 跨行跨页怎么处理"。
> 这三条是 Agent 1 的核心定义，只有写检查器的人会真的想清楚。
> 其余 6 个由 C 写，判据机械，不需要 A 拍板。

## 1. 框架

- [ ] 1.1 `app/verifier/registry.py`：检查器列表 + 统一执行 + 异常隔离
- [ ] 1.2 检查器签名 `check(state) -> list[Issue]`，只读不写
- [ ] 1.3 单检查器异常 → `level="fail"` 的 Issue，其余继续
- [ ] 1.4 verdict 计算：任一 fail → fail；仅有 warn → warn；全通过 → pass
- [ ] 1.5 `stages` 中有非 `done` 的必需阶段时 verdict 不得为 pass
- [ ] 1.6 `Issue` 构造 helper，统一 `checker` / `level` / `finding_ids` / `location` / `detail`

## 2. C 负责的检查器

### schema_check

- [ ] 2.1 必填键缺失 → fail
- [ ] 2.2 枚举越界（`status` / `kind` / `severity` / `input_mode`）→ fail
- [ ] 2.3 `field_keys` 为 null → fail
- [ ] 2.4 `Finding.id` 前缀与 `source` 不匹配 → fail
- [ ] 2.5 `applicable_rules` 缺 `chunk_id` → fail
- [ ] 2.6 `FieldValue.notes` 为 null → warn

### trail_check

- [ ] 2.7 越界 op（`summarize` / `rewrite` / `drop`）→ fail，`location` 为条目 ID
- [ ] 2.8 未声明的 `agent` 值 → fail
- [ ] 2.9 `extracted` 字段无对应 `emit` → warn
- [ ] 2.10 `llm_call` 缺 `prompt_hash` → warn
- [ ] 2.11 `op="pass"` 缺 `detail.reason` → warn
- [ ] 2.12 `trail` 为空但 `fields` 非空 → fail

### conflict_check

- [ ] 2.13 `input_mode="raw"` 时跳过并记 `StageReport(skipped)`
- [ ] 2.14 Agent 2 判值非法而 Agent 3 以其为前提 → fail
- [ ] 2.15 Agent 2 报 missing 而 Agent 3 引为既有事实 → fail
- [ ] 2.16 同规则相反结论 → warn
- [ ] 2.17 不比"合规/不合规"标签

### coverage_check

- [ ] 2.18 `unavailable=true` 但 summary 未声明 → fail
- [ ] 2.19 `unavailable=false` 但 `retrieved` 空 → fail
- [ ] 2.20 `raw` 模式无 `business_type` 却未标 `uncertain` → fail
- [ ] 2.21 声称覆盖某法域但无对应 chunk → warn
- [ ] 2.22 `escalate=false` 但 risk 类 claim 全 insufficient → warn

### citation_check

- [ ] 2.23 `chunk_id` 不在 `retrieved` → fail
- [ ] 2.24 关键实体不在被引 chunk 原文 → fail
- [ ] 2.25 国别正则 MUST 用 ISO 3166-1 白名单过滤（`\b[A-Z]{2}\b` 会误命中 BY/IN）
- [ ] 2.26 `insufficient` 却带 `chunk_id` → warn

### finding_anchor_check

- [ ] 2.27 `field_keys` 不存在于 `fields` / `extra_fields` → fail
- [ ] 2.28 `evidence` 为空 → fail
- [ ] 2.29 `citation` 与 `source` 不匹配 → warn
- [ ] 2.30 `critical` 无 `suggestion` → warn

## 3. A 负责的检查器

- [ ] 3.1 `provenance_check`：`extracted` 但 `source` 为 null → fail
- [ ] 3.2 `provenance_check`：`span` 归一化后不在对应文件全文 → fail
- [ ] 3.3 `provenance_check`：`source.file_id` 不在 `docs` 中 → fail
- [ ] 3.4 `provenance_check`：`span` 超长 → warn
- [ ] 3.5 `provenance_check`：MUST 调用共享层 `normalize_ws`，不得私有实现
- [ ] 3.6 C 接入注册表，**不修改 A 的判据**
- [ ] 3.7 A 在实现时同步确认：最小片段定义、归一化变换清单、跨行跨页处理

## 4. 可信度

- [ ] 4.1 `provenance_coverage`：`(claimed - failed) / max(1, claimed)`
- [ ] 4.2 `citation_support`：`supported / max(1, cited)`
- [ ] 4.3 `inferred_unconfirmed_rate`：`unconfirmed_inferred / max(1, total_fields)`
- [ ] 4.4 分母为 0 时返回 `1.0`，不得返回 `0.0`
- [ ] 4.5 不做加权合成
- [ ] 4.6 `score` 存在时与三个比率同时展示，且不参与判定

## 5. 受控重跑

- [ ] 5.1 `can_repair()`：仅 `fail` 级 + 预算未耗尽 + 非 schema 问题 + 非输入类失败
- [ ] 5.2 `build_feedback()`：由 `Issue.detail` + `location` 组装，不含分数
- [ ] 5.3 归因路由：`trail`/`provenance`→agent1，`citation`/`coverage`→agent3，`conflict`→agent2+agent3
- [ ] 5.4 预算：`repair_count < 1` 且 `recheck_count + repair_count < 3`
- [ ] 5.5 耗尽后降级人工复核并标注重跑次数
- [ ] 5.6 `repair` 不回 `reset`

## 6. 测试

- [ ] 6.1 `test_checker_exception_does_not_abort`
- [ ] 6.2 `test_checker_exception_becomes_fail`
- [ ] 6.3 `test_credibility_ratios_recomputable`（两人独立算，结果一致）
- [ ] 6.4 `test_zero_denominator_is_one_not_zero`
- [ ] 6.5 `test_score_does_not_affect_verdict`
- [ ] 6.6 `test_stage_failed_cannot_pass`
- [ ] 6.7 `test_schema_check.py` 三条
- [ ] 6.8 `test_trail_check.py` 六条
- [ ] 6.9 `test_conflict_check.py` 三条
- [ ] 6.10 `test_coverage_check.py` 四条
- [ ] 6.11 `test_citation_check.py` 三条（含 ISO 白名单）
- [ ] 6.12 `test_provenance_check.py` 四条（含共用归一化）
- [ ] 6.13 `test_finding_anchor_check.py` 两条
- [ ] 6.14 `test_repair.py` 七条
- [ ] 6.15 用 gold 样本校准：确保正常样本能走到导出，不被检查器误拦

## 7. 验收

- [ ] 7.1 虚构 `chunk_id` 被 `citation_check` 拦下（fail）
- [ ] 7.2 人为在 trail 里塞一条 `rewrite`，`trail_check` 报 fail
- [ ] 7.3 `retrieved=[]` + summary 写"未发现问题" → `coverage_check` 报 fail
- [ ] 7.4 三个比率能由任一成员用 state 复算一致
- [ ] 7.5 正常样本不被误拦（`verdict != fail`）
- [ ] 7.6 重跑反馈能让第二次明显改善（用具体失败项而非分数验证）
- [ ] 7.7 Agent 4 单独触发被明确拒绝
- [ ] 7.8 每个检查器至少有一次在真实样本上触发（证明不是空转）
