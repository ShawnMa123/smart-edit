# Tasks: Agent 1 标准化

> Owner: A
> 前置：`poc-skeleton` 的契约（2.x）与共享层（3.x）完成，`fixtures/` 四对快照可用
> `parse` / `extract` / `normalize` 的实现在 `poc-skeleton`（共享层）。
> 本 change 负责：字段字典、归一化基准定义、业务类型判定、Agent 1 侧的留痕与 Finding、测试与接缝断言。
> 判定口径以 `design.md`（v2）为准；代码落位见《编排层实施设计》§6.2–§6.4。

## 1. 字段字典

- [x] 1.1 `fields.yaml`：保函核心字段 12-15 个，每个含 `key` / `label` / `aliases` / `type` / `required`
- [x] 1.2 每条约束标注 `stage` 归属（`normalize` 归 A，`validate` 归 B）
- [x] 1.3 `max_length` / `charset` / `precision` / `thousands` / `date_order` 全部挂到 `stage.normalize`
- [x] 1.4 日期类字段显式声明 `date_order`（`DMY` / `MDY` / `null`），不得缺省
- [x] 1.5 `required` 必须显式写 `true` / `false`（A 靠它决定是否补 `missing` 占位，缺省按可选处理）
- [ ] 1.6 与 B 对齐：确认没有同一条约束被两边各实现一遍；`required` 只由 B 判阻断
- [x] 1.7 启动期校验：`fields.yaml` 缺失/解析失败 → 三阶段 `failed`，**不得**用空字典继续跑

## 2. 归一化基准（共享层，A 定义，全层共用）

- [x] 2.1 `normalize_ws` 五步固定顺序：NFKC → 剔除零宽字符 → 连字符归一 → 引号归一 → 空白折叠
- [x] 2.2 `MAX_SPAN_LEN = 200` 作为共享常量从 `app/parsing/normalize.py` 导出
- [x] 2.3 单测覆盖：全半角、`U+2011`、弯引号、零宽字符、跨行空白
- [x] 2.4 在 docstring 写明**不做**大小写折叠/去标点/同义词换算（附理由）
- [ ] 2.5 通知 C：`provenance_check` 必须 import 同一函数，不得私有实现

## 3. 解析（行为验证，实现由共享层提供）

- [x] 3.1 文本型 PDF 产出 `page`（有 bbox 时一并产出）
- [x] 3.2 粘贴文本与纯文本邮件 `page` / `bbox` 为 `null`
- [x] 3.3 扫描件返回明确错误，不返回空 `full_text`
- [x] 3.4 单文件失败不影响其余文件
- [x] 3.5 `tests/test_parse.py` 覆盖以上四条 + 两条路径解析一致

## 4. 抽取

- [x] 4.1 prompt 四条硬约束：逐字复制 / span 最小片段 / 保持大小写 / 找不到就不输出
- [x] 4.2 候选含 `key` / `raw_value` / `span` / `label` / `confidence` / `doc_type`，并组装 `_source`
- [x] 4.3 `extract()` 为纯函数，返回 `ExtractResult(candidates, trail_entries, model_calls, failed_batches)`
- [x] 4.4 分批按 `blocks` 累加，**不切断 block**；超预算 block 单独成批并记 `oversize_block`
- [x] 4.5 `locate_span()` 回填 `page` / `bbox`：只在单一 block 内命中，找不到返回 `(None, None)`
- [x] 4.6 输出不合 schema → 重试一次 → 二次失败进 `failed_batches`，阶段记 `partial`
- [x] 4.7 解析失败的文件不抽取，但必须记 `op="pass"` + `detail.reason`
- [x] 4.8 `confidence` **不得**写入 `FieldValue`（契约无此字段）

## 5. 规范化

- [x] 5.1 金额 → `Decimal` 2 位小数，`normalized_from` 保留原值
- [x] 5.2 币种 → ISO 4217；日期 → ISO 8601（含 `date_order`）；`integer` 去单位后缀
- [x] 5.3 名称 → 仅去首尾空白，**保持原文大小写与拼写**
- [x] 5.4 `span_locatable()` 只在字段自己的 `file_id` 内比对；跨文件命中 → `inferred`
- [x] 5.5 `classify()` 三分支 + `DOWNGRADING_NOTES`（带任一降级 note 即降级）
- [x] 5.6 `required` 缺候选 → `missing` 占位 + `notes=["not_in_source"]` + `pass` 留痕；可选字段不占位
- [x] 5.7 超 `max_length` → 截断 + `notes=["value_truncated"]` + `inferred` + Finding 草稿（**无 id**）
- [x] 5.8 字典外字段 → `extra_fields`，绝不混进 `fields`
- [x] 5.9 只执行 `stage=normalize` 的约束，不执行 `stage=validate`
- [x] 5.10 跨页 span → `notes=["merged_across_pages"]` + `op="transform"` + `detail.cross_page` + `inferred`
- [x] 5.11 span 超 `MAX_SPAN_LEN` → 先按句末标点切；切不出 → `notes=["span_oversize"]` + `inferred`

## 6. Finding 编号

- [x] 6.1 `app/findings.py::materialize_findings(state, drafts)`（A 提供，B/C 复用）
- [x] 6.2 编号续号：读已有 `findings` 的最大序号 +1，重跑不撞号
- [x] 6.3 每条 Finding 必须写一条 `op="emit"` 留痕
- [x] 6.4 `blocking` 恒为 `false`、`resolved` 恒为 `false`、`resolution` 恒为 `null`
- [ ] 6.5 通知 B/C：三个前缀共用同一实现，不得各写一份计数器

## 7. 业务类型

- [x] 7.1 四级判决表 + 词表（强指示词 / 一般词 / 其他已知类型 / 无依据）
- [x] 7.2 每条分支写 `op="pass"` 留痕，`detail` 含 `business_type` / `evidence` / `reason`
- [x] 7.3 无依据 → `unsupported`，**不得**为让下游跑通而臆断
- [x] 7.4 唯一写入者：`normalize`；`ingest` 只透传；Agent 3 raw 模式推断只写 `legal.coverage`

## 8. 留痕

- [x] 8.1 每个产出字段至少一条 `transform`（`before` / `after` / `ref`）
- [x] 8.2 模型调用记 `model` 与 `prompt_hash`
- [x] 8.3 `missing` 占位、业务类型判定、解析失败未抽取都记 `pass` 且带理由
- [x] 8.4 全流程不出现 `summarize` / `rewrite` / `drop`
- [x] 8.5 重跑后 `trail` 只增不减（append-only）

## 9. 独立触发

- [x] 9.1 只 `parse` 时不产出 `fields` / `extra_fields` / `business_type`
- [x] 9.2 `parse → extract` 时不写 `fields`（只产出 `_candidates`）
- [x] 9.3 三档登记为 stage target；未登记目标必须 `409`，不得静默跑全链
- [x] 9.4 同一 PDF 经独立触发与完整流程，`blocks` 逐块一致
- [x] 9.5 `_candidates` 用后即清（`Overwrite([])`），不留在 checkpoint 里

## 10. 接缝 fixture（`agent-contract` spec 的义务）

- [x] 10.1 `fixtures/seam_a_to_b/input.json`：至少含一条 `extracted`、一条 `inferred`、一条 `missing`
- [x] 10.2 `fixtures/seam_a_to_b/assert.py`：大小写保持 / span 在自身文件可定位 / `notes` 是 `[]` 不是 `null` / 字典外字段只在 `extra_fields` / `confirmed=false` / `edited_by_user=false` / PDF 字段 `page` 非空
- [x] 10.3 `fixtures/seam_a_to_c/input.json` + `assert.py`：`full_text` 与原文逐字一致（不含摘要）/ `business_type` 唯一来源
- [x] 10.4 断言写成可执行 pytest，**不得**写完整输出金文件（下游内容依赖各自规则，只有断言稳定）

## 11. 验收

- [ ] 11.1 3 份样本端到端跑通，`fields` 非空
- [ ] 11.2 每个 `extracted` 字段的 `span` 能人工在原文中搜到（抽 20 个）
- [ ] 11.3 `inferred` 占比低于 30%
- [ ] 11.4 全流程 trail 中不出现 `summarize` / `rewrite` / `drop`
- [ ] 11.5 名称类字段大小写与原文一致（抽 20 个人工核对）
- [ ] 11.6 `provenance_check` 对 3 份样本零 `fail`
- [ ] 11.7 `override`：故意把某字段 span 改成别处的文字，`provenance_check` 必须报 `fail`（证明检查器不是摆设）
- [x] 11.8 造一份缺必填字段的材料，`fields` 里出现 `status="missing"` 而非键缺席
- [x] 11.9 造一份超长金额，出现截断 + `value_truncated` + `N-` Finding
- [x] 11.10 `business_type` 在全文写点只有一处（`normalize`）