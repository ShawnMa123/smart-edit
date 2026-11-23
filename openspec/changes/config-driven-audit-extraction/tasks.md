# Tasks

## 1. Extraction profile 配置

- [x] 1.1 新增 `app/configs/extraction/guarantee-default.json`：按 `fields.yaml` key 声明 `guarantee_amount / currency / issue_date / expiry_date / governing_rules / payment_terms` 的 labels、`value_kind`、`search`、`max_chars` 与置信度；验证：JSON 可被 loader 读取，且不包含内联正则/脚本
- [x] 1.2 实现 profile loader（JSON 解析、`value_kind` 白名单、与 `fields.yaml` key 对账、profile id/version/content hash）：`app/configs` 或 `app/parsing` 新模块；验证：单测覆盖合法 profile、未知 key、不支持 `value_kind`、非法 JSON
- [x] 1.3 为 profile 增加发布状态与 `document_types` 校验（未发布/类型不匹配拒绝）；验证：单测覆盖拒绝路径与可读错误

## 2. 确定性提取器

- [x] 2.1 新增 `app/parsing/deterministic_extract.py`：按 label/alias 在单个 block 内定位，支持 `same_block` / `same_or_next_block`，产出 candidate（`key/raw_value/span/confidence/_source`）；验证：单测覆盖金额、日期、币种、文本与跨 block 场景
- [x] 2.2 复用现有金额/日期/币种规范化（Decimal、`date_order`、币种），不复制 `normalize_ws` / 金额逻辑；验证：单测断言 `12/03/26`、`USD 500,000.00` 的解析结果与 `normalize` 一致
- [x] 2.3 实现候选去重与冲突降级：同值去重、不同值标 `unconfirmed`、写 trail、不得静默选择；验证：单测覆盖多值冲突与重复值
- [x] 2.4 修改 `app/nodes/extract.py`：有 profile 时走确定性路径且 `llm=None` 不失败，`model_calls=0`，报告 reason 记录 profile id/version；无 profile 保持原 fixture/LLM 路径；验证：节点单测覆盖两条路径
- [x] 2.5 在 `verification` 增加 extraction provenance（source/profile id/version/hash/fields_found/fields_missing）；验证：audit 投影单测覆盖 deterministic 与 fixture 两种来源

## 3. 审计基准日与相对日期

- [x] 3.1 在 `app/rules/dsl.py` 增加受控 `relative_date` 操作数，仅允许 `today`；验证：DSL 单测覆盖 `today` 通过、其他值加载失败
- [x] 3.2 在 `app/rules/engine.py` 从 `context["as_of"]` 解析 `today`，保持引擎无系统时钟依赖；验证：`tests/test_rule_engine.py` 用固定 `as_of` 覆盖过去/当天/未来日期
- [x] 3.3 `audit_state` / `audit_node` / audit API 接受 `as_of`（缺省服务器当天并回显），报告记录 `as_of`；验证：单测覆盖显式 `as_of` 与同一输入重放一致

## 4. 公司与模板策略

- [x] 4.1 新增 `app/rules/bundles/company-guarantee.yaml`：Issue Date 不得早于 `today`、金额上限、必含 URDG 758/付款条款、允许币种；每条规则包含 test vectors；验证：rule bundle 加载、`doctor` 与规则单测通过
- [x] 4.2 在 template 增加可选 `extraction_profile`，并实现解析顺序（请求 `?profile=` > template > 无 profile）；显式 profile 不跳过 template/clauses/公司包；验证：单测覆盖三种来源、未知/未发布/类型不匹配拒绝
- [x] 4.3 冲突与缺包行为接入现有 `find_conflicts` / `unable_to_assess`：公司包与客户模板 gate 冲突时不得 `allowed`；验证：单测覆盖冲突、未发布包、单包内多规则不误报
- [x] 4.4 在 `verification.policy` 记录 template id、bundle 版本与 `as_of`；验证：报告单测覆盖 provenance 块

## 5. 前端与文档

- [x] 5.1 Audit/Assistant 面板显示 extraction source、profile 版本、`as_of`、字段覆盖与冲突提示；验证：组件测试覆盖 deterministic/fixture、字段缺失、冲突三种展示
- [x] 5.2 更新 `how_to_use.md` / `README.md`：fixture 仅用于 demo、确定性 profile 的配置位置、公司规则与 `as_of` 含义、如何新增字段/规则；验证：文档中的示例 profile 路径与命令实际存在且可执行
- [x] 5.3 为 3 份样例文本（正常、Issue Date 在过去、金额缺失/为负）加入回归 fixture/测试；验证：样例在 deterministic 路径产生预期 findings，且不依赖网络

## 6. 集成与回归

- [x] 6.1 端到端验证：修改 editor 文本中的 issue date / amount 后，audit findings 随文本变化，证明不再读取 fixture；验证：集成测试或手工步骤记录实际输出
- [x] 6.2 兼容性验证：无 profile、fixture 模式、`AUTH_MODE=fake` 路径保持原行为，报告明确标注来源；验证：既有测试 + 新增兼容测试通过
- [x] 6.3 回归：`.venv/bin/python -m pytest tests -q`、`npm --prefix web run typecheck`、`npm --prefix web run test`、`openspec validate config-driven-audit-extraction --strict`；验证：四条命令通过

## Workflow follow-up

- 评审通过后归档本 change。
- 豆包语义复核（provider、advisory findings、span 校验）留到后续 change。