# Tasks: Agent 2 要件校验

> Owner: B
> 前置：`poc-skeleton` 契约冻结；`agent-normalize` 的 `fields.yaml` 中 `stage` 标签就位

## 1. 要件清单

- [ ] 1.1 `requirements.yaml`：`guarantee` 的必备字段（含 `blocking` 声明）
- [ ] 1.2 `requirements.yaml`：`guarantee` 的必备单据（含 `detect` 关键词列表）
- [ ] 1.3 `requirements.yaml`：业务限制（期限上限、金额上下限）
- [ ] 1.4 与业务方确认清单内容（不可自行推断）

## 2. 前置校验与入口

- [ ] 2.1 校验 `fields` 非空、`business_type` 非空，缺失时返回结构化拒绝
- [ ] 2.2 `business_type = unsupported` → 跳过全部检查，`StageReport(status="skipped")`
- [ ] 2.3 `requirements.yaml` 缺该类型 → `StageReport(status="failed")`
- [ ] 2.4 独立触发入口：先清除 `source="business"` 的旧 findings，再写入

## 3. 检查节点

- [ ] 3.1 `pick_checklist`：按 `business_type` 取清单
- [ ] 3.2 `check_fields`：格式类校验，只执行 `fields.yaml` 中 `stage=validate` 的约束
- [ ] 3.3 `check_fields`：语义类校验 —— 值不属于该栏目内容（纯数字名称、"详见附件"、"N/A"）
- [ ] 3.4 `check_fields`：产出 Finding 但不修改 `fields`
- [ ] 3.5 `check_completeness`：关键词预判 + 模型判定双判
- [ ] 3.6 `check_completeness`：区分 `missing` / `not_found`
- [ ] 3.7 `check_rules`：日期先后、金额精度、金额范围、期限上限、币种有效性
- [ ] 3.8 每个检查节点各写 `StageReport`

## 4. Finding

- [ ] 4.1 统一构造函数，`id` 用 `B-` 前缀自增
- [ ] 4.2 `blocking` 由 `requirements.yaml` 规则声明决定，不由 `severity` 推导
- [ ] 4.3 `not_found` 恒不阻断
- [ ] 4.4 `evidence` 必须含具体值与违反的约束
- [ ] 4.5 `resolved=false` / `resolution=null`
- [ ] 4.6 无关联字段时 `field_keys=[]`（非 `None`）

## 5. 标注与评测（spec 见 `specs/eval-benchmark/`）

- [ ] 5.1 收集 / 脱敏 5-10 份样本到 `eval/samples/`（该目录不入库）
- [ ] 5.2 `eval/gold/<sid>.json`：每字段含 `value` + `tolerance`（`exact`/`numeric`/`date`/`fuzzy:<阈值>`）
- [ ] 5.3 `eval/gold/<sid>.json`：`files` 只写 POC 支持的格式，不得含 Word/Excel/扫描件
- [ ] 5.4 `eval/gold_rules/<sid>.json`：每项含 `kind` / `rule_id` / `severity` / `blocking` / `field_keys` / `note`
- [ ] 5.5 标注口径：只标"业务上应该报什么"，不看模型实际输出
- [ ] 5.6 分歧处两人各标一半再交叉复核，不得单人决定
- [ ] 5.7 L1 指标按字段类型分别报 P/R/F1，另报整份零错误率与推断率
- [ ] 5.8 出处准确率：抽 30 个 `extracted` 字段人工确认 `span` 可定位（不得用程序代替）
- [ ] 5.9 L2 指标：blocking 漏报数（最关键）+ 误报数
- [ ] 5.10 `eval/report.md` 按 spec 的报告范围写：报什么、不报什么、必须声明哪些限制

## 6. 测试

- [ ] 6.1 `test_missing_vs_not_found_produce_different_kind`
- [ ] 6.2 `test_not_found_is_not_blocking`
- [ ] 6.3 `test_missing_required_field_is_blocking`
- [ ] 6.4 `test_unsupported_business_type_zero_blocking`
- [ ] 6.5 `test_empty_fields_rejected_not_empty_findings`
- [ ] 6.6 `test_field_value_not_modified_by_checker`
- [ ] 6.7 `test_evidence_is_not_vague`
- [ ] 6.8 `test_rules.py` 覆盖 5 条业务参数规则
- [ ] 6.9 `test_verify_standalone.py` 覆盖拒绝与 findings 重跑不累加

## 7. 验收

- [ ] 7.1 3 份样本跑通，findings 全部带可定位的 `field_keys` 或 `evidence`
- [ ] 7.2 不支持的 `business_type` 时零 blocking
- [ ] 7.3 全套输出中无任何"合规/不合规"结论措辞
- [ ] 7.4 `missing` 与 `not_found` 在同一份样本上都能复现
