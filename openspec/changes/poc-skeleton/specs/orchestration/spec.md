# Orchestration

## Purpose

编排能力为 POC 提供唯一的状态通道与执行主干：它把解析、抽取、标准化做成共享阶段，
用阶段状态区分"检查过无问题"与"没检查"，用操作日志记录对原文的每次自由操作，
并在导出前以可判定的闸门决定放行或拦截。它不产出业务结论，只保证流程可解释、可复算、可拦截。

## ADDED Requirements

### Requirement: 统一状态契约

系统 SHALL 使用单一 `EditState` 作为所有节点的唯一数据通道，节点输入输出 MUST 通过该结构传递，不得使用自由文本或私有对象交接。

#### Scenario: 节点返回部分更新
- **WHEN** 任一节点执行完毕
- **THEN** 该节点只返回自己负责的键，未返回的键保持原值

#### Scenario: reducer 收敛范围
- **WHEN** 新增一个 state 键
- **THEN** 该键 MUST NOT 使用 reducer，除非同时满足"由多个并行分支写入"且"语义为追加"
- **AND** POC 中允许 reducer 的键 ONLY `findings`、`trail`、`stages`

#### Scenario: 临时通道不得被依赖
- **WHEN** 任何 Agent 需要判定业务结论
- **THEN** MUST NOT 读取 `_candidates`
- **AND** `normalize` 完成时 MUST 用 `Overwrite([])` 清空 `_candidates`

#### Scenario: 循环内累加键重置
- **WHEN** 图因用户修改字段而回到 `reset`
- **THEN** `reset` MUST 用 `Overwrite` 清空 `findings`，其余循环键（`legal` / `retrieved` / `verification` / `gate` / `export`）MUST 用普通赋值置空
- **AND** MUST NOT 清空 `stages` 与 `trail`（审计历史只能追加）

### Requirement: 键的写入权唯一

系统 SHALL 保证每个 state 键只有唯一写入者，使并行分支不会静默覆盖彼此结果。

#### Scenario: 业务类型唯一写入
- **WHEN** 需要确定 `business_type`
- **THEN** `ingest` MUST 只透传入参，唯一写入者 MUST 是 `normalize`
- **AND** Agent 3 在 `raw` 模式推断的类型 MUST 只写入 `legal.coverage`

#### Scenario: 验证报告唯一写入
- **WHEN** 任一 Agent 想写 `verification`
- **THEN** ONLY `agent4` MAY 写入，其他 Agent MUST NOT 写

#### Scenario: 并行写集受限
- **WHEN** `agent2` 与 `agent3` 在同一超级步并行
- **THEN** 两者写集交集 MUST 仅限 `findings` / `trail` / `stages`

### Requirement: 主图执行顺序

系统 SHALL 按 `ingest → parse → extract → normalize → reset → (agent2 ‖ agent3) → merge → agent4 → hitl → gate → export` 执行完整流程。

#### Scenario: 标准化先于校验
- **WHEN** 一次完整运行开始
- **THEN** `agent2` 与 `agent3` MUST 在 `normalize` 完成后才开始，且两者并行执行

#### Scenario: 交叉校验在合并之后
- **WHEN** `agent2` 与 `agent3` 均已完成
- **THEN** `merge` 先排序去重，`agent4` 再执行证据链校验

#### Scenario: 首次运行与重跑同一条路径
- **WHEN** 首次运行在 `findings` 为空时进入 `reset`
- **THEN** `reset` MUST 照常执行（`Overwrite([])` 幂等），MUST NOT 为首次运行另设分支

#### Scenario: 用户修改字段后的重跑范围
- **WHEN** 用户在核对台修改了字段并要求重新校验
- **THEN** 系统 MUST 从 `reset` 重新开始，只重跑 `agent2` / `agent3` / `agent4`
- **AND** MUST NOT 重跑 `parse` / `extract` / `normalize`

#### Scenario: 重跑次数上限
- **WHEN** `recheck_count` 达到 3
- **THEN** 系统 MUST 跳过重跑，直接进入 `gate`

#### Scenario: 闸门失败不回核对台
- **WHEN** `gate` 返回 `blocked`
- **THEN** 系统 MUST 结束本次运行并返回全部拦截原因，MUST NOT 回到 `hitl`

#### Scenario: 并行不使用动态扇出
- **WHEN** 需要并行处理多份文件
- **THEN** 并发 MUST 收敛在 `parse` 节点内部
- **AND** MUST NOT 用 `Send` 让多个分支写同一个无 reducer 的键

### Requirement: 解析与抽取为共享阶段

`parse`、`extract`、`normalize` SHALL 实现为共享层的纯函数，MUST NOT 由任一 Agent 私有实现，且 MUST NOT 依赖 `state`。

#### Scenario: 同一文档的解析结果一致
- **WHEN** 同一文件分别经完整流程与独立触发被解析
- **THEN** 两次产出的 `ParsedDoc.blocks` MUST 逐块一致

#### Scenario: 抽取只有一个实现
- **WHEN** Agent 1 与"只跑要件校验"的独立触发都需要从原文抽取字段
- **THEN** 两者 MUST 调用同一个 `extract` 实现

#### Scenario: 共享层不写日志
- **WHEN** `parse` / `extract` / `normalize` 执行完毕
- **THEN** 三者 MUST NOT 直接写 `state`
- **AND** 留痕 MUST 以 `trail_entries` 返回，由节点 `record_many()` 写回

#### Scenario: 解析失败不中断全图
- **WHEN** 某个文件无法解析
- **THEN** MUST 写入该 `ParsedDoc.errors` 并写 `StageReport(status="partial"/"failed", reason=…)`
- **AND** MUST NOT 抛异常终止整次运行，也 MUST NOT 返回空 `full_text` 冒充成功

### Requirement: 阶段可独立触发

系统 SHALL 允许调用方只触发部分阶段而不运行完整流程，并按目标自动补齐其声明的前置阶段。

#### Scenario: 用户直接扫描原始文档
- **WHEN** 调用方请求只运行 `agent3` 并直接提供原始文件
- **THEN** 系统 MUST 自动补跑 `parse`，MUST NOT 要求先跑完 Agent 1
- **AND** `legal.input_mode` MUST 为 `raw`

#### Scenario: 用户只跑要件校验
- **WHEN** 调用方请求只运行 `agent2`
- **THEN** 系统 MUST 自动补跑 `parse → extract → normalize`

#### Scenario: 只跑到抽取
- **WHEN** 调用方请求 `stages=extract`
- **THEN** 系统 MUST 补跑 `parse` 并只写 `_candidates`
- **AND** MUST NOT 写 `fields`

#### Scenario: Agent 4 通过 `audit` target 单独触发
- **WHEN** 调用方请求只运行 `agent4`
- **THEN** 系统 MUST 将其解析为已登记的 `audit` target
- **AND** MUST 自动补跑 `parse → extract → normalize`，并在 `fields` 非空后执行审计
- **AND** 未登记的目标仍 MUST 返回 `unknown_stage`，MUST NOT 静默跑完整流程

#### Scenario: 未登记的目标
- **WHEN** 调用方请求一个未在阶段表中登记的目标
- **THEN** 系统 MUST 返回 `unknown_stage` 错误
- **AND** MUST NOT 静默跑完整流程

#### Scenario: 独立触发前清理上一轮产出
- **WHEN** 对同一运行再次独立触发某 Agent
- **THEN** MUST 先清空该 Agent 负责的那一类结论，避免 reducer 叠加出重复条目
- **AND** MUST NOT 清空 `stages` 与 `trail`

### Requirement: 前置条件必须显式声明

每个 Agent SHALL 在阶段表中声明前置阶段与必需的非空 state 键，MUST NOT 在前置缺失时静默返回空结果。

#### Scenario: 声明形式
- **WHEN** 新增或修改一个 Agent
- **THEN** MUST 在 `app/stages.py` 登记 `requires_stages`、`requires_keys`、`produces`、`standalone`

#### Scenario: 前置缺失时拒绝执行
- **WHEN** Agent 2 被触发但 `fields` 为空或 `business_type` 为空
- **THEN** 系统 MUST 拒绝并返回缺失项清单
- **AND** MUST NOT 返回 `findings = []` 作为结果

#### Scenario: 拒绝与零结果的区分
- **WHEN** 一个 Agent 因前置缺失未执行
- **THEN** 其 `StageReport.status` MUST NOT 为 `done`
- **AND** 系统 MUST 返回统一的拒绝结构（含 `refused`、`missing`、`agent`）

#### Scenario: 拒绝必须可判定分支
- **WHEN** 调用方收到拒绝
- **THEN** 响应 MUST 带机器可读的 `code`（`REFUSED` / `NOT_STANDALONE` / `unknown_stage`）

### Requirement: 阶段状态可区分"没问题"与"没检查"

系统 SHALL 为每个执行阶段写入 `StageReport`，使"检查过且无问题"与"未检查"在数据结构上可区分。

#### Scenario: 检查通过但零发现
- **WHEN** 某 Agent 完成检查且未产出任何 Finding
- **THEN** 其 `StageReport` MUST 为 `{status: "done", produced: 0}`

#### Scenario: 未执行
- **WHEN** 某 Agent 因前置缺失、超时或错误未完成
- **THEN** 其 `StageReport.status` MUST 为 `skipped` / `failed` / `partial` 之一，且 `reason` MUST 非空

#### Scenario: 部分完成必须阻断
- **WHEN** 存在 `status="partial"` 的必需阶段
- **THEN** 该状态 MUST 参与闸门判定并阻断导出，MUST NOT 视为通过

#### Scenario: 阶段记录只追加
- **WHEN** 同一阶段被执行多次（重跑）
- **THEN** 系统 MUST 追加新的 `StageReport`，MUST NOT 覆盖历史
- **AND** 读取方 MUST 以同名阶段的最后一条为准

#### Scenario: 下游不得据未执行推断无问题
- **WHEN** `gate` 或 `agent4` 读到一个 `status != "done"` 的阶段
- **THEN** MUST NOT 将其视为"未发现问题"，MUST 在结论中显式标注该阶段未完成

#### Scenario: 共享阶段有唯一归因
- **WHEN** `parse` / `extract` / `normalize` 写入 `StageReport`
- **THEN** `agent` MUST 记为共享阶段所有者（`agent1`），使回放可归因

### Requirement: 自由操作必须留痕

系统 SHALL 记录每个 Agent 对原文与中间结果的全部自由操作，使结果可逐步追溯。

#### Scenario: 抽取必留痕
- **WHEN** 任一 Agent 调用模型产出字段、Finding 或 claim
- **THEN** MUST 写入至少一条 `TrailEntry`，含 `before`、`after` 与 `ref`

#### Scenario: 越界操作必被记录
- **WHEN** Agent 对原文执行概括、改写或丢弃
- **THEN** `TrailEntry.op` MUST 记为 `summarize` / `rewrite` / `drop` 之一

#### Scenario: 合理的整体性跳过不算越界
- **WHEN** Agent 因范围原因未处理部分内容
- **THEN** MUST 记为 `op="pass"` 并在 `detail` 说明理由，MUST NOT 记为 `drop`

#### Scenario: 模型调用可复现定位
- **WHEN** 发生一次模型调用
- **THEN** `TrailEntry` MUST 记录 `model` 与 `prompt_hash`

#### Scenario: 日志非空
- **WHEN** 任一 Agent 完成执行（含占位实现）
- **THEN** `trail` MUST NOT 为空

### Requirement: 受控重跑

系统 SHALL 在证据链检查失败时允许有限次重跑，MUST 只由可判定检查触发。

#### Scenario: 可判定检查失败触发重跑
- **WHEN** Agent 4 的某个可修复检查器返回 `level="fail"` 且 `repair_count < 1`
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

#### Scenario: 只清理被重跑分支
- **WHEN** 重跑 `agent2` 或 `agent3` 中的一条分支
- **THEN** 系统 MUST 只清空该分支的结论，保留另一条分支的结果
- **AND** MUST 保留 `verification` 作为本次重跑的反馈通道

### Requirement: 人工核对暂停

系统 SHALL 在发布结果前暂停，等待用户确认或修改字段，并在恢复后从中断点继续。

#### Scenario: 触发暂停
- **WHEN** `agent4` 完成
- **THEN** `hitl` MUST 通过 `interrupt()` 暂停并返回自包含的核对面板数据（字段表 + findings + 三方结论 + stages）

#### Scenario: 面板必须暴露未确认项
- **WHEN** 存在 `status="inferred"` 且 `confirmed=false` 的字段
- **THEN** 核对面板 MUST 让用户能直接看出该字段未确认

#### Scenario: 跨进程恢复
- **WHEN** 调用方使用同一 `thread_id` 提交 `Command(resume=...)`
- **THEN** 系统 MUST 从中断点恢复，且此前的状态不丢失
- **AND** MUST NOT 重跑 `parse` / `extract`

#### Scenario: 暂停节点可重入
- **WHEN** `hitl` 节点因 resume 而重新执行
- **THEN** 该节点在调用 `interrupt()` 之前 MUST NOT 执行模型调用或写库操作

#### Scenario: 用户修改留痕
- **WHEN** 用户在核对台修改字段值
- **THEN** 系统 MUST 置 `confirmed=true`、`edited_by_user=true`、保留旧值到 `normalized_from`
- **AND** MUST 写入一条 `op="transform"` 的留痕

#### Scenario: 重复 resume 幂等
- **WHEN** 同一 resume payload 被提交两次
- **THEN** 系统 MUST 只生效一次，MUST NOT 重复写库或重复累加 `recheck_count`

### Requirement: 闸门判定

系统 SHALL 在导出前同步判定是否允许导出，并按固定顺序返回全部拦截原因。

#### Scenario: 证据链失败时阻断
- **WHEN** `verification` 缺失或 `verification.verdict` 为 `fail`
- **THEN** `gate` MUST 返回 `blocked` 并给出原因

#### Scenario: 存在未处理阻断项
- **WHEN** 存在 `blocking: true` 且 `resolved: false` 的 Finding
- **THEN** `gate` MUST 返回 `blocked` 并列出未处理项 ID

#### Scenario: 未确认的推断值
- **WHEN** 存在 `status="inferred"` 且 `confirmed=false` 的字段
- **THEN** `gate` MUST 返回 `blocked`

#### Scenario: 关键阶段未完成
- **WHEN** 任一必需阶段（`ingest` / `parse` / `extract` / `normalize` / `agent2` / `agent3` / `agent4`）的 `StageReport.status` 不为 `done`
- **THEN** `gate` MUST 返回 `blocked`，MUST NOT 视为通过

#### Scenario: 法规结论要求人工
- **WHEN** `legal.escalate_to_human` 为 `true` 或 `legal.coverage.unavailable` 非空
- **THEN** `gate` MUST 返回 `blocked` 并分别标注 `LEGAL_ESCALATED` / `COVERAGE_UNAVAILABLE`

#### Scenario: 判定不确定
- **WHEN** 规则缺失或数据异常导致无法判定
- **THEN** `gate` MUST 返回 `blocked`，不得默认放行

#### Scenario: 原因一次全返回
- **WHEN** 同时存在多条拦截原因
- **THEN** `gate` MUST 一次返回全部原因，MUST NOT 短路只返回第一条

#### Scenario: 分数不参与判定
- **WHEN** `verification.score` 很低但所有可判定检查通过
- **THEN** `gate` MUST NOT 因分数阻断
- **AND** `score` MAY 出现在判定结果中用于展示

#### Scenario: 闸门只产判定
- **WHEN** `gate` 返回 `pass`
- **THEN** 导出动作由后端服务执行，生产环境的导出服务 MUST 独立复核一次，不得直接信任图内结果

### Requirement: 导出标准文件

系统 SHALL 在闸门通过后产出结构化标准文件并写入不可变版本。

#### Scenario: 导出内容
- **WHEN** `gate` 返回 `pass`
- **THEN** 系统 MUST 输出包含 `doc_id`、`snapshot_id`、`run_id`、`business_type`、`fields`、`verification`、`gate`、`exported_at`、`version_no` 的 JSON

#### Scenario: 拦截时不产出文件
- **WHEN** `gate` 返回 `blocked`
- **THEN** 系统 MUST NOT 产出可导入的标准文件，只返回拦截原因
- **AND** 导出节点 MUST 以 `StageReport(status="skipped")` 记录，防止路由写错时静默导出

#### Scenario: 版本号不可由调用方指定
- **WHEN** 写入导出版本
- **THEN** 版本号 MUST 由存储层自增生成，调用方 MUST NOT 指定

### Requirement: 运行可观测与幂等

系统 SHALL 支持按节点粒度回放一次运行，并保证重复请求不产生重复结果。

#### Scenario: 查看执行轨迹
- **WHEN** 一次运行结束
- **THEN** 调用方 MUST 能按 `thread_id` 获取节点执行顺序、`StageReport` 与 `TrailEntry`

#### Scenario: 查询结果必含阶段状态
- **WHEN** 调用方读取一次运行的结果
- **THEN** 响应 MUST 包含 `stages`
- **AND** 缺失 `stages` MUST 被视为实现缺陷（前端无法区分"没问题"与"没检查"）

#### Scenario: 重复提交
- **WHEN** 同一请求被重复提交或在服务重启后重放
- **THEN** 系统 MUST NOT 重复写版本、重复发通知或重复累加重跑计数