# Agent Contract

## Purpose

接缝契约定的是两位开发者之间的交接语义，而不是图内节点的实现细节：字段值保持原文形态、
出处可定位、文档与原文逐字一致、每次自由操作都留痕、阻断与抑制各有唯一依据。
三人各自实现 Agent 时不看主图，但必须看这一份；改动其中任一条即视为破坏接缝。

## ADDED Requirements

### Requirement: 冻结边界

系统 SHALL 明确区分可自由修改的实现细节与不可单方面修改的接缝契约（状态键语义、共享层签名、fixture）。

#### Scenario: 可自由修改
- **WHEN** 成员调整某 Agent 的内部节点划分、prompt、算法、目录结构、日志粒度
- **THEN** 无需他人同意，只要不改变本 spec 声明的接缝

#### Scenario: 不可自由修改
- **WHEN** 改动涉及 `EditState` 键的语义、共享层函数签名、或本 spec 中任一条目
- **THEN** MUST 三人一致同意，且 MUST 同步更新对应 fixture

#### Scenario: 内部改动影响共享层
- **WHEN** 某成员想合并或拆分 subgraph 内部节点
- **THEN** MAY 自由调整，但 `parse` / `extract` / `normalize` 三个函数 MUST 仍可独立调用
- **AND** 其他 Agent 的独立触发能力 MUST NOT 受影响

#### Scenario: 新增字段必须可选
- **WHEN** 需要给已冻结的子结构加字段
- **THEN** 该字段 MUST 为可选（`NotRequired`），MUST NOT 修改既有字段含义

### Requirement: 共享层是纯函数

`parse` / `extract` / `normalize` SHALL 以纯函数形式提供，MUST NOT 接收 `state`，MUST NOT 直接写日志。

#### Scenario: 签名不含 state
- **WHEN** 为共享层新增或修改函数
- **THEN** 函数签名 MUST NOT 出现 `state` 参数，使其可在无图状态下单测

#### Scenario: 留痕通过回执返回
- **WHEN** 共享层产生需要留痕的操作（模型调用、转换、产出）
- **THEN** 留痕条目 MUST 随回执返回（`ExtractResult.trail_entries` / `NormalizeResult.trail_entries`）
- **AND** MUST 由节点用 `record_many()` 写回 `state`

#### Scenario: 抽取是唯一模型入口
- **WHEN** 需要从原文抽取候选字段
- **THEN** ONLY `extract` MAY 调用模型
- **AND** `parse` MUST 为 0 次模型调用，`normalize` MUST 为纯代码

### Requirement: 定位基准唯一

系统 SHALL 提供唯一的文本归一化基准，任何"两个字符串是否指向同一段原文"的判定 MUST 走它。

#### Scenario: 归一化规则必须共用
- **WHEN** 任何代码需要判断"两个字符串是否指向同一段原文"
- **THEN** MUST 调用共享层的 `normalize_ws`，MUST NOT 各自实现一份
- **理由**：Agent 1 用该规则判定 `extracted`，Agent 4 用该规则校验 `extracted`；两份实现一旦分叉，全部字段会被误判为不合规且极难定位

#### Scenario: 归一化常量唯一
- **WHEN** 需要判断 span 是否超长
- **THEN** MUST import 共享层的 `MAX_SPAN_LEN`，MUST NOT 各自写死一个数字

#### Scenario: 归一化边界明确
- **WHEN** 实现 `normalize_ws`
- **THEN** MUST 按 NFKC 全半角 → 零宽字符剔除 → 连字符归一 → 引号归一 → 空白折叠的顺序执行
- **AND** MUST NOT 做大小写折叠、去标点或同义词换算

### Requirement: 接缝一 · A → B 字段契约

Agent 1 SHALL 向 Agent 2 交付满足以下语义的字段表。

#### Scenario: 值保持原文形态
- **WHEN** 原文写作 `ABC Trading Pte Ltd`
- **THEN** `FieldValue.value` MUST 为 `ABC Trading Pte Ltd`
- **AND** MUST NOT 转大写、纠正拼写或去标点
- **理由**：比对时双方各自归一化；若提前大写，合规场景要展示的客户原文就丢了

#### Scenario: 出处是最小片段
- **WHEN** 原文写作 `申请人：ABC Trading Pte Ltd 地址：新加坡`
- **THEN** `source.span` MUST 为 `ABC Trading Pte Ltd`
- **AND** MUST NOT 包含栏目标签或相邻字段

#### Scenario: 三分类可信
- **WHEN** `status="extracted"`
- **THEN** `source.span` MUST 能在该 `file_id` 的原文中定位（按共享 `normalize_ws`）
- **AND** 下游 MAY 据此免除人工核对

#### Scenario: 必需的缺失必须占位
- **WHEN** `fields.yaml` 标记 `required: true` 的字段无任何候选
- **THEN** MUST 产出 `status="missing"`、`value=null`、`notes=["not_in_source"]` 的占位
- **AND** MUST NOT 让该字段在 `fields` 中缺席

#### Scenario: 初始状态
- **WHEN** Agent 1 产出一个字段
- **THEN** `confirmed` MUST 为 `false`，`edited_by_user` MUST 为 `false`

#### Scenario: 空列表而非 null
- **WHEN** 产出 `FieldValue.notes`
- **THEN** 无说明时 MUST 为 `[]`，MUST NOT 为 `null`

#### Scenario: 字典外字段隔离
- **WHEN** 抽取出 `fields.yaml` 未定义的字段
- **THEN** MUST 只出现在 `extra_fields`，MUST NOT 混入 `fields`

#### Scenario: 候选不得冒充字段
- **WHEN** 只跑 `parse → extract`
- **THEN** 候选 MUST 只存在于 `_candidates`
- **AND** MUST NOT 写入 `fields`（未规范化、未三分类的值不满足契约）

#### Scenario: Agent 2 不得改写
- **WHEN** Agent 2 执行校验
- **THEN** MUST NOT 修改 `fields` / `extra_fields` 中的任何值或状态
- **AND** 校验结论 MUST 只以 `Finding` 表达

### Requirement: 接缝二 · A → C 文档契约

Agent 1 SHALL 向 Agent 3 交付与原文逐字一致的文档。

#### Scenario: 全文不得改写
- **WHEN** Agent 3 读取 `docs[].full_text`
- **THEN** 该文本 MUST 与原文逐字一致
- **AND** MUST NOT 是摘要、拼接重构或规范化后的版本

#### Scenario: 业务类型的唯一来源
- **WHEN** 需要 `business_type`
- **THEN** MUST 只由 `normalize` 写入 `EditState.business_type`（`ingest` 只透传入参）
- **AND** Agent 3 在 `raw` 模式下推断出的类型 MUST 只写入 `legal.coverage`，MUST NOT 写回 `EditState.business_type`
- **理由**：谁写的必须唯一可查；否则 Agent 4 无法判断该值的出处

#### Scenario: 解析结果复用
- **WHEN** 独立触发某 Agent 时 `docs` 已存在且 `SourceFile.sha256` 未变化
- **THEN** 系统 MUST 复用已有的 `docs`，MUST NOT 重复解析
- **AND** 若文件内容变化，MUST 重新解析并清除依赖旧 `docs` 的全部下游结果

#### Scenario: 解析失败不冒充成功
- **WHEN** 某文件解析失败
- **THEN** 该 `ParsedDoc.errors` MUST 非空，且该文件 MUST NOT 参与后续字段判定
- **AND** MUST NOT 用空 `full_text` 让下游误以为原文为空

### Requirement: 接缝三 · 全体 → D 留痕契约

每个 Agent SHALL 按统一约定写入操作日志。

#### Scenario: 产出一律留痕
- **WHEN** 任一 Agent 产出字段、Finding 或 claim
- **THEN** MUST 写入对应 `emit` 条目，含 `after`（产出值）与 `ref`（来源）

#### Scenario: 模型调用一律留痕
- **WHEN** 任一 Agent 调用模型
- **THEN** MUST 写入 `llm_call` 条目，含 `model` 与 `prompt_hash`

#### Scenario: 跳过必须说明理由
- **WHEN** 因范围原因未处理部分输入
- **THEN** MUST 记为 `op="pass"` 且 `detail.reason` 非空
- **AND** MUST NOT 记为 `drop`

#### Scenario: 日志 ID 不得跨 Agent 冲突
- **WHEN** 生成 `TrailEntry.id`
- **THEN** MUST 为 `{agent}.{stage}#{n:03d}`，`n` 在该 Agent 内自增

#### Scenario: 日志非空
- **WHEN** 任一 Agent 完成执行
- **THEN** `trail` MUST NOT 为空
- **AND** 占位实现同样 MUST 写至少一条

### Requirement: 接缝四 · B/闸门 与 D/闸门 的判定依据

Agent 2 与 Agent 4 SHALL 以互不重叠的依据影响闸门判定。

#### Scenario: 阻断项来自 Finding
- **WHEN** 闸门判定是否存在未处理的阻断项
- **THEN** MUST 只读 `findings` 中 `blocking=true` 且 `resolved=false` 的条目
- **AND** MUST NOT 依据 `FieldValue.status` 单独判定阻断

#### Scenario: 抑制发布来自 verification
- **WHEN** 闸门判定证据链是否成立
- **THEN** MUST 只读 `verification.verdict`
- **AND** Agent 2 MUST NOT 写入 `verification`

#### Scenario: 新增 Finding 的初始状态
- **WHEN** Agent 1 / 2 / 3 产出一条 Finding
- **THEN** `resolved` MUST 为 `false`，`resolution` MUST 为 `null`
- **AND** 只有人工核对节点 MAY 修改这两个字段

#### Scenario: 阻断由规则声明
- **WHEN** Agent 2 产出 Finding
- **THEN** `blocking` MUST 由 `requirements.yaml` 的规则声明决定
- **AND** Agent 4 MUST NOT 修改任何 Finding 的 `blocking`

#### Scenario: 检查器只读
- **WHEN** Agent 4 的检查器执行
- **THEN** 检查器签名 MUST 为 `(state) -> list[Issue]`，MUST NOT 写任何 state 键
- **AND** 阶段记录 MUST 由 `agent4` 节点统一聚合后写入

### Requirement: 前置声明

每个 Agent SHALL 声明其前置阶段与必需的非空状态键。

#### Scenario: 声明形式
- **WHEN** 新增或修改一个 Agent
- **THEN** MUST 在 `app/stages.py` 中登记其 `requires_stages`、`requires_keys`、`produces`、`standalone`

#### Scenario: Agent 2 的前置
- **WHEN** 触发 Agent 2
- **THEN** 必需 `fields` 非空且 `business_type` 非空
- **AND** `docs` 缺失时 MAY 降级为仅依据字段判定，并在 `StageReport` 说明

#### Scenario: Agent 3 的前置
- **WHEN** 触发 Agent 3
- **THEN** `enriched` 模式必需 `docs` + `fields` + `business_type`
- **AND** `raw` 模式只需 `files`，由系统自动补跑 `parse`

#### Scenario: Agent 4 的前置
- **WHEN** 触发 Agent 4
- **THEN** 必需至少一个其他 Agent 的 `StageReport(status="done")`
- **AND** 无任何上游产出时 MUST 拒绝执行

#### Scenario: 拒绝格式统一
- **WHEN** 前置不满足
- **THEN** MUST 返回 `{"refused": true, "missing": [...], "agent": "...", "reason": "..."}`
- **AND** MUST NOT 返回空结果或部分结果

### Requirement: fixture 是接缝的验收载体

系统 SHALL 为每个接缝提供一份输入快照与一份断言集。

#### Scenario: 四对接缝 fixture
- **WHEN** 契约冻结
- **THEN** `fixtures/` 下 MUST 存在四对：`seam_a_to_b`、`seam_a_to_c`、`seam_ac_to_d`、`seam_bd_to_gate`
- **AND** 每对含 `input.json`（上游产出快照）与 `assert.py`（下游应满足的断言）

#### Scenario: 断言而非金文件
- **WHEN** 编写接缝的期望侧
- **THEN** MUST 写成可执行的断言（pytest）
- **AND** MUST NOT 写成完整输出金文件
- **理由**：下游输出的具体内容依赖各自的业务规则（如 `requirements.yaml`），只有断言是稳定的

#### Scenario: 互为验收
- **WHEN** 成员 A 修改了自己的产出
- **THEN** 其余成员的 `assert.py` MUST 仍然通过
- **AND** 失败即视为破坏接缝，MUST 三人共同确认后才可修改断言

#### Scenario: 语义被 fixture 固定
- **WHEN** 存在语义歧义（大小写、片段粒度、空值形态）
- **THEN** MUST 以 fixture 中的具体取值为准，MUST NOT 以口头约定为准