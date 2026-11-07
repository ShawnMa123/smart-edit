# Orchestration

## ADDED Requirements

### Requirement: 统一状态契约

系统 SHALL 使用单一 `EditState` 作为所有节点的数据通道，节点的输入与输出 MUST 通过该结构传递，不得使用自由文本交接。

#### Scenario: 节点返回部分更新
- **WHEN** 任一节点执行完毕
- **THEN** 该节点只返回自己负责的键，未返回的键保持原值

#### Scenario: 并行分支写入同一键
- **WHEN** `agent2` 与 `agent3` 在同一 super-step 内并行执行并都写入 `findings`
- **THEN** `findings` MUST 使用合并 reducer（`operator.add`），两边结果均被保留

#### Scenario: 循环内累加键重置
- **WHEN** 图因用户修改字段而回到 `reset`
- **THEN** `reset` MUST 使用 `Overwrite` 清空 `findings`、`legal`、`retrieved`、`verification`，避免结果重复累加

#### Scenario: reducer 收敛范围
- **WHEN** 新增一个 state 键
- **THEN** 该键 MUST NOT 使用 reducer，除非它同时满足"由多个并行分支写入"且"语义为追加"
- **AND** POC 中允许 reducer 的键 ONLY `findings`、`trail`、`stages`

### Requirement: 主图执行顺序

系统 SHALL 按 `ingest → parse → extract → normalize → reset → (agent2 ‖ agent3) → merge → agent4 → hitl → gate → export` 的顺序执行完整流程。

#### Scenario: 标准化先于校验
- **WHEN** 一次完整运行开始
- **THEN** `agent2` 与 `agent3` MUST 在 `normalize` 完成后才开始，且两者并行执行

#### Scenario: 交叉校验在合并之后
- **WHEN** `agent2` 与 `agent3` 均已完成
- **THEN** `merge` 先排序去重，`agent4` 再执行跨 Agent 一致性校验

#### Scenario: 用户修改字段后的重跑范围
- **WHEN** 用户在核对台修改了字段并要求重新校验
- **THEN** 系统 MUST 从 `reset` 重新开始，只重跑 `agent2`/`agent3`/`agent4`，MUST NOT 重跑解析与抽取阶段

#### Scenario: 重跑次数上限
- **WHEN** `recheck_count` 达到 3
- **THEN** 系统 MUST 跳过重跑，直接进入 `gate`

#### Scenario: 闸门失败不回核对台
- **WHEN** `gate` 返回 `blocked`
- **THEN** 系统 MUST 结束本次运行并返回拦截原因，MUST NOT 回到 `hitl` 重新触发暂停

### Requirement: 解析与抽取为共享阶段

`parse`、`extract`、`normalize` SHALL 实现为共享层，MUST NOT 由任一 Agent 私有实现。

#### Scenario: 同一文档的解析结果一致
- **WHEN** 同一文件分别经完整流程与独立触发被解析
- **THEN** 两次产出的 `ParsedDoc.blocks` MUST 逐块一致

#### Scenario: 抽取只有一个实现
- **WHEN** Agent 1 与"只跑要件校验"的独立触发都需要从原文抽取字段
- **THEN** 两者 MUST 调用同一个 `extract` 实现，MUST NOT 各自实现一份

### Requirement: 阶段可独立触发

系统 SHALL 允许调用方只触发部分阶段而不运行完整流程。

#### Scenario: 用户直接扫描原始文档
- **WHEN** 调用方请求只运行 `agent3` 并直接提供原始文件
- **THEN** 系统 MUST 自动补跑 `parse`，MUST NOT 要求先跑完 Agent 1
- **AND** `legal.input_mode` MUST 为 `raw`

#### Scenario: 用户只跑要件校验
- **WHEN** 调用方请求只运行 `agent2`
- **THEN** 系统 MUST 自动补跑该 Agent 声明的前置阶段

#### Scenario: Agent 4 不可单独触发
- **WHEN** 调用方请求只运行 `agent4`
- **THEN** 系统 MUST 拒绝，因为其校验对象是其他 Agent 的输出

### Requirement: 前置条件必须显式声明

每个 Agent SHALL 声明其前置阶段与必需的非空 state 键，MUST NOT 在前置缺失时静默返回空结果。

#### Scenario: 前置缺失时拒绝执行
- **WHEN** Agent 2 被触发但 `fields` 为空或 `business_type` 为空
- **THEN** 系统 MUST 拒绝执行并返回缺失项清单
- **AND** MUST NOT 返回 `findings = []` 作为结果

#### Scenario: 拒绝与零结果的区分
- **WHEN** 一个 Agent 因前置缺失未执行
- **THEN** 其 `StageReport.status` MUST NOT 为 `done`

### Requirement: 阶段状态可区分"没问题"与"没检查"

系统 SHALL 为每个执行阶段写入 `StageReport`，使"检查过且无问题"与"未检查"在数据结构上可区分。

#### Scenario: 检查通过但零发现
- **WHEN** 某 Agent 完成检查且未产出任何 Finding
- **THEN** 其 `StageReport` MUST 为 `{status: "done", produced: 0}`

#### Scenario: 未执行
- **WHEN** 某 Agent 因前置缺失、超时或错误未完成
- **THEN** 其 `StageReport.status` MUST 为 `skipped` / `failed` / `partial` 之一，且 `reason` MUST 非空

#### Scenario: 下游不得据未执行推断无问题
- **WHEN** `gate` 或 `agent4` 读到一个 `status != "done"` 的阶段
- **THEN** 其 MUST NOT 将该阶段视为"未发现问题"，MUST 在结论中显式标注该阶段未完成

### Requirement: 自由操作必须留痕

系统 SHALL 记录每个 Agent 对原文与中间结果的全部自由操作，使结果可逐步追溯。

#### Scenario: 抽取必留痕
- **WHEN** 任一 Agent 调用模型产出字段、Finding 或 claim
- **THEN** MUST 写入至少一条 `TrailEntry`，含 `before`（原文片段）、`after`（产出值）与 `ref`

#### Scenario: 越界操作必被记录
- **WHEN** Agent 对原文执行概括、改写或丢弃
- **THEN** `TrailEntry.op` MUST 记为 `summarize` / `rewrite` / `drop` 之一

#### Scenario: 合理的整体性跳过不算越界
- **WHEN** Agent 因范围原因未处理部分内容（如仅抽取与业务相关的页面）
- **THEN** MUST 记为 `op="pass"` 并在 `detail` 说明理由，MUST NOT 静默跳过

#### Scenario: 模型调用可复现定位
- **WHEN** 发生一次模型调用
- **THEN** `TrailEntry` MUST 记录 `model` 与 `prompt_hash`

### Requirement: 受控重跑

系统 SHALL 在证据链检查失败时允许有限次重跑，MUST 只由可判定检查触发。

#### Scenario: 可判定检查失败触发重跑
- **WHEN** `agent4` 的某个检查器返回 `level="fail"` 且 `repair_count < 1`
- **THEN** 系统 MAY 重跑受影响的分支，并把失败项作为反馈传入

#### Scenario: 分数不触发重跑
- **WHEN** `verification.score` 偏低但所有可判定检查均通过
- **THEN** 系统 MUST NOT 触发重跑

#### Scenario: 重跑必须携带具体失败项
- **WHEN** 触发重跑
- **THEN** 反馈 MUST 包含失败项定位与期望，MUST NOT 只传分数

#### Scenario: 不可重试的失败
- **WHEN** 失败原因属于输入问题（文件无法解析、原文确实缺数据）
- **THEN** 系统 MUST NOT 重跑，MUST 直接降级为人工复核

#### Scenario: 重跑预算
- **WHEN** `repair_count` 达到 1 或总重跑次数达到 3
- **THEN** 系统 MUST 停止重跑并降级为人工复核

### Requirement: 人工核对暂停

系统 SHALL 在发布结果前暂停，等待用户确认或修改字段，并在恢复后从中断点继续。

#### Scenario: 触发暂停
- **WHEN** `agent4` 完成
- **THEN** `hitl` MUST 通过 `interrupt()` 暂停并返回核对面板数据

#### Scenario: 跨进程恢复
- **WHEN** 调用方使用同一 `thread_id` 提交 `Command(resume=...)`
- **THEN** 系统 MUST 从中断点恢复，且此前的状态不丢失

#### Scenario: 暂停节点可重入
- **WHEN** `hitl` 节点因 resume 而重新执行
- **THEN** 该节点在调用 `interrupt()` 之前 MUST NOT 执行模型调用或写库操作

### Requirement: 闸门判定

系统 SHALL 在导出前同步判定是否允许导出。

#### Scenario: 证据链失败时阻断
- **WHEN** `verification.verdict` 为 `fail`
- **THEN** `gate` MUST 返回 `blocked` 并给出原因

#### Scenario: 存在未处理阻断项
- **WHEN** 存在 `blocking: true` 且 `resolved` 为 `false` 的 Finding
- **THEN** `gate` MUST 返回 `blocked` 并列出未处理项 ID

#### Scenario: 未确认的推断值
- **WHEN** 存在 `status="inferred"` 且 `confirmed=false` 的字段
- **THEN** `gate` MUST 返回 `blocked`

#### Scenario: 关键阶段未完成
- **WHEN** 任一必需阶段的 `StageReport.status` 不为 `done`
- **THEN** `gate` MUST 返回 `blocked`，MUST NOT 视为通过

#### Scenario: 判定不确定
- **WHEN** 规则缺失或数据异常导致无法判定
- **THEN** `gate` MUST 返回 `blocked`，不得默认放行

#### Scenario: 闸门只产判定
- **WHEN** `gate` 返回 `pass`
- **THEN** 导出动作由后端服务执行，生产环境的导出服务 MUST 独立复核一次，不得直接信任图内结果

### Requirement: 导出标准文件

系统 SHALL 在闸门通过后产出结构化标准文件。

#### Scenario: 导出内容
- **WHEN** `gate` 返回 `pass`
- **THEN** 系统 MUST 输出包含 `doc_id`、`snapshot_id`、`run_id`、`business_type`、`fields`、`verification`、`gate`、`exported_at` 的 JSON

#### Scenario: 拦截时不产出文件
- **WHEN** `gate` 返回 `blocked`
- **THEN** 系统 MUST NOT 产出可导入的标准文件，只返回拦截原因

### Requirement: 运行可观测

系统 SHALL 支持按节点粒度回放一次运行。

#### Scenario: 查看执行轨迹
- **WHEN** 一次运行结束
- **THEN** 调用方 MUST 能按 `thread_id` 获取各节点的执行顺序、`StageReport` 与 `TrailEntry`
