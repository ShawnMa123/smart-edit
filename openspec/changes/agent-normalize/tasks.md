# Tasks: Agent 1 标准化

> Owner: A
> 前置：`poc-skeleton` 的契约（2.x）与共享层（3.x）完成，`fixtures/` 四对快照可用

> `parse` / `extract` / `normalize` 的实现在 `poc-skeleton`（共享层）。
> 本 change 负责：字段字典、业务类型判定、Agent 1 侧的留痕与 Finding、以及本 Agent 的测试。

## 1. 字段字典

- [ ] 1.1 `fields.yaml`：保函核心字段 12-15 个，每个含 `key` / `label` / `aliases` / `type`
- [ ] 1.2 `fields.yaml`：每条约束标注 `stage` 归属（`normalize` 归 A，`validate` 归 B）
- [ ] 1.3 `fields.yaml`：日期类字段声明 `date_order`，未声明的显式留空
- [ ] 1.4 与 B 对齐：确认没有同一条约束被两边各实现一遍

## 2. 解析（行为验证，实现由共享层提供）

- [ ] 2.1 验证文本型 PDF 产出 `page` / `bbox`
- [ ] 2.2 验证粘贴文本与纯文本邮件 `page` / `bbox` 为 `null`
- [ ] 2.3 验证扫描件返回明确错误，不返回空字符串
- [ ] 2.4 验证单文件失败不影响其余文件
- [ ] 2.5 `tests/test_parse.py` 覆盖以上四条

## 3. 抽取

- [ ] 3.1 `extract` prompt：明确要求"必须逐字复制原文片段作为 span，不得改写、不得拼接跨段落内容"
- [ ] 3.2 `extract`：候选字段含 `key` / `raw_value` / `span` / `label` / `confidence`
- [ ] 3.3 `extract`：输出不合 schema 重试一次，二次失败置 `StageReport(status="partial")`
- [ ] 3.4 `extract`：长文档分批，记录每批处理范围
- [ ] 3.5 相关性过滤掉的页面记 `op="pass"` 并写明理由

## 4. 规范化

- [ ] 4.1 金额 → `Decimal` 2 位小数，`normalized_from` 保留原值
- [ ] 4.2 币种 → ISO 4217 三位大写
- [ ] 4.3 日期 → ISO 8601，含 `date_order` 与 `notes=["date_ambiguous"]`
- [ ] 4.4 名称 → 仅去首尾空白，**保持原文大小写与拼写**
- [ ] 4.5 三分类判定，定位前先归一化空白 / 全半角 / 连字符
- [ ] 4.6 未定义字段 → `extra_fields`
- [ ] 4.7 超长字段 → 截断 + `notes` + Finding `N-xxx`（`severity="warn"`）
- [ ] 4.8 只执行 `stage=normalize` 的约束，不执行 `stage=validate`

## 5. 业务类型

- [ ] 5.1 判定依据优先取文档明确标识（`GUARANTEE` / `保函` / `URDG 758`）
- [ ] 5.2 依据记录到 trail
- [ ] 5.3 无依据 → `unsupported`，不得臆断

## 6. 留痕

- [ ] 6.1 每个产出字段至少一条 `TrailEntry`（`before` / `after` / `ref`）
- [ ] 6.2 模型调用记录 `model` 与 `prompt_hash`
- [ ] 6.3 `tests/test_agent1_trail.py`：全字段可追溯；范围性跳过记为 `pass` 而非 `drop`

## 7. 独立触发验证

- [ ] 7.1 只 `parse` 时不产出 `fields`
- [ ] 7.2 `parse → extract` 时不写入 `fields`（未经规范化的值不满足契约）
- [ ] 7.3 同一 PDF 经独立触发与完整流程，`blocks` 逐块一致

## 8. 验收

- [ ] 8.1 3 份样本端到端跑通，`fields` 非空
- [ ] 8.2 每个 `extracted` 字段的 `span` 能人工在原文中搜到
- [ ] 8.3 `inferred` 占比低于 30%
- [ ] 8.4 全流程 trail 中不出现 `summarize` / `rewrite` / `drop`
- [ ] 8.5 名称类字段大小写与原文一致（抽 20 个字段人工核对）
