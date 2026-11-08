# 优化方案 —— 规范审计组（`agent-audit`）

> 基于当前实现（**30/31 任务、281 个测试全绿**、引擎零模型调用、每份保函 **51 个计划单元**）给出。
> 全部条目都有实测依据或代码位置，按"能立刻做 / 需要人拍板 / 以后再说"排序。
> 本文与 `REVIEW.zh-CN.md` 是给团队看的中文支持文档；`proposal/specs/design/tasks` 仍保持英文。

## 0. 现状快照

| 指标 | 实测值 |
|---|---|
| 计划单元 / 份保函 | 51（schema 39 + 规则 6 + 证据 6） |
| 干净文档评估率 | 0.647（33/51） |
| 全推断文档评估率 | 0.020（1/51） |
| 引擎模型调用 | 0 |
| 单次审计耗时（48.4k 字符、15 字段） | **19.9 ms**（O1 优化后；优化前 **314 ms**） |
| 规则包 | `guarantee-core` v1.0.0，6 条规则，每条带 pass/finding/needs_input 向量 |
| 传输层 | `POST /runs/{tid}/stages/audit`（`agent4` 同一实现），信封带 `verification` / `gate` |

## 1. P0 — 已清空（`0.1` 除外）

| 任务 | 内容 | 状态 |
|---|---|---|
| `0.1` | 与 `agent-verify` 的边界会签（B 编写规则包、本组负责引擎与闸门） | **仍待 B**：一次性会签 + 两处文档，不阻塞代码 |
| `0.2` | 冻结文件批准：`Issue` 4 个可选字段 + `VerificationReport.audit` + `agent4.standalone` 翻转 | ✅ A 已批准并实施（2026-11-08），B/C 追认待签 |
| `3.3` | 报告落进 `verification.audit`（快照摘要 / schema 版本 / 规则包版本 / 引擎版本 / stale） | ✅ `app/audit/project.py` |
| `4.1`–`4.3` | 单元 → `Issue`、规则失败 → `Finding`（填 `gate_type` / `target_operations` / `method` / `check_id`）+ 锚点解析 | ✅ `project.py` + runner 的两个守卫 |
| `6.1` | `app/nodes/audit.py`（调纯函数、写 `StageReport`、回 trail，无模型调用） | ✅ 含失败仍出 `StageReport` |
| `6.2` | 注册 `audit` 阶段目标（可独立触发） | ✅ `STAGE_TARGETS["audit"]` + `AGENT_TARGETS` |
| `6.3` | 信封暴露 `verification` 与 `gate` | ✅ 二者恒在；`null` 表示"还没审 / 没人问闸门" |

顺序（已按此执行）：`0.2` → `6.1` → `3.3` → `4.x` → `6.2` → `6.3`。
每步验证：`6.1` 用节点测试（`tests/test_audit_node.py`）；`3.3` 断言报告字段；`4.x` 断言
`Issue`/`Finding` 的四个字段与锚点（`tests/test_audit_project.py`）；`6.2/6.3` 用 `TestClient`
（`tests/test_api.py`）。

> 落地时发现的三个新约束（见 `design.md` D13）：`audit` 目标必须声明**整条**共享链（`execute_chain`
> 不做传递展开）；契约 `Finding` 没有 `gate_type`，因此闸门改读 `verification.audit["findings"]`
> （否则每个硬阻断都会静默降级成 advisory）；节点只在**点名操作**时才写 `gate`。

## 2. P1 — 技术债与缺陷

### 2.1 本轮已修（供 review 时对照）

| # | 问题 | 修法 |
|---|---|---|
| 1 | 字段比较用原始字符串（`USD` vs `0` 恒为类型不匹配） | 按 schema 类型强制（`Decimal` / `date.fromisoformat` …），不隐式转换 |
| 2 | **`integer` vs `decimal` 装载器允许、引擎却判失败**（新发现） | 数值类型统一提升为 `Decimal` 比较；`bool` 排除在外 |
| 3 | `datetime` 是 `date` 子类，date 字段 vs datetime 字面量会"可比"后在比较时崩 | 精确类型判断，把这类问题变成装载期错误 |
| 4 | 规则写错字段名只在运行时降级为"无法评估" | `validate_against_schema()`：未知字段 / 不可比字面量 **装载期报错** |
| 5 | `value_unparsable`（文档坏）与 `rule_type_mismatch`（规则坏）共用原因码 | 拆分，规则坏 → `failed`（会显形） |
| 6 | 报告说不出"评了多少" | `coverage{assessed, not_applicable, unsettled, ratio}` + 闸门 R1/R2/R3 |
| 7 | `allowed` 是光秃秃的 | 决策带 `coverage` / `open_gaps` / `advisory_finding_ids` / `unsupported_capability` |
| 8 | 规则包冲突无测试 | 补"两个已发布版本冲突 → 报告无法判定 + 闸门阻断"用例 |
| 9 | **O1** 每次定位 span 都重新归一化整篇全文（48.4k 字符 × 15 字段 = **314 ms**，单次 `normalize_ws` 仅 19 ms） | `normalized_full_texts()` 一次归一化 + `span_locatable(..., normalized=)` / `locate_span(..., normalized_blocks=)` 复用；实测 **314 ms → 19.9 ms（≈16×）**，两个新参数均可选，旧调用不受影响 |
| 10 | **O2** 冲突检测漏"跨规则包 `gate_type` 相反"（一个 `hard_block`、一个 `advisory`） | 扩为 `(field_id, category)` 跨包不一致检测；**同一包内**同时存在两种 `gate_type` 不算冲突（2 条测试，含"我们自己的包必须干净"） |
| 11 | **O4** 规则向量只要求"至少 1 个 pass" | 门禁提升为 **pass + finding + needs_input 各至少一条**；补 4 条向量 |
| 12 | **O5** `audit_state(snapshot_digest="unknown")` 默认值会让人忘记传 | 改为必填参数，缺省抛 `AuditRunError`（报告必须能说出它审的是哪个快照） |

### 2.2 待修（建议按此顺序）

| # | 问题与实测 | 方案 | 代价 | 需谁同意 |
|---|---|---|---|---|
| **O3** | `value_unparsable` 现在落到 `unable_to_assess`（无法判定），但业务上更像"请人工修值"（`needs_input`） | 归入 `_INPUT_REASONS`（一行） | 一行 + 1 测试 | **B**（改变闸门语义） |
| **O6** | 覆盖率阈值写死在 `policy.py` 常量，所有文档类型共用 | 迁移到规则包的 `coverage_profile`（`AI-audit §4.3` 已有此概念），按文档类型给不同阈值 | 1 天 | C（规则包结构） |
| **O7** | 内部原因码（`checker_crashed` 等）直接出现在报告里 | 对外映射层：内部 reason_code → 客户可读文案（`AUD-13` 数据最小化要求） | 0.5 天 | B（对外口径） |

## 3. P2 — 功能缺口（按 AUD 映射，不建议塞进本 change）

| 缺口 | 说明 | 何时做 | 依赖 |
|---|---|---|---|
| `AUD-10` 语义检查 + 机器 Reviewer | 本构建**没有** `method=semantic` 的任何产出，报告字段已预留 | 独立 change | 模型 provider + 准则模板 |
| `AUD-07` 变量多处引用 | 无变量模型 | 待 `AUTO-02` 落地 | 文档模型 |
| `AUD-08/09/11` 模板与内部政策包 | 无模板实体 | 待业务提供模板 | 业务方 |
| `AUD-15/17` 草稿导出、应用建议 | 属宿主 Command 层 | 随编辑器 | `editor-shell` |
| `AUD-18/19` 权限、`AUD-20` 治理、`AUD-21` 异步 | 无 DB / 无队列 | 上生产前 | 基础设施 |
| 证据族 3 项（引用支持 / 结论冲突 / 覆盖声明） | 现在 `not_applicable` + 原因码，**不是通过** | B/C 落地后自动可执行 | `agent-verify`、`agent-regulatory` |

## 4. P3 — 交付与可观测

1. **UI 接入（后端已就绪，剩前端一行）**：`editor-shell` 的"规范审计"按钮改指 `stages/audit`（现在错指
   `normalize`），并显示"51 项中评估了 X 项" + 缺口数 + advisories —— 数据都在信封的
   `verification.checks` / `verification.audit.coverage` / `gate` 里。`6.2/6.3` 已完成，此项只等前端改动。
2. ✅ **已做** CI 门禁：`pytest`（254）+ 规则向量门禁（`test_rule_bundles.py`）+ 性能基准
   `tests/test_audit_perf.py`（断言"整篇只归一化一次"+ 0.5 s 灾难线，锁住 O1 不回归）。
3. ✅ **已做** 演示脚本固化：`scripts/audit_demo.py`（`--json` 可选）一条命令打印计划、三种文档的
   评估率/结论/闸门决策 + 过期拒答；见 `DEMO.md`。
4. ✅ **已做** 规则包体检：`python -m app.rules.doctor`（`app/rules/doctor.py`）一次回答规则负责人发布前的四个问题 ——
   字段引用与字面量类型是否可评、两个已发布来源是否互相矛盾、每条规则的向量是否仍能演示
   `pass`/`finding`/`needs_input`、计划单元数（schema/rule/evidence 分族）。退出码即门禁：
   `0` 健康、`1` 发现问题、`2` 规则包根本装不进来（避免"什么都没查"读成"一切正常"）；
   `--json` 供 CI 使用。已固化为 `tests/test_rule_doctor.py`（12 个用例）。

## 5. 现在**不建议**做的（避免过度优化）

| 想法 | 为什么不做 |
|---|---|
| 并行化 51 个单元的求值 | 单次审计毫秒级；O1 修完更快，并发只增加复杂度 |
| 给 DSL 写编译器 / 缓存层 | 规则数量是个位数，Python 直接求值足够 |
| POC 阶段做 `AUD-20` 规则发布审批流 | 最大风险是规则写错，已由"装载期校验 + 向量门禁"覆盖 |
| 用模型"补语义"绕开无法表达的规则 | 直接毁掉 AT-01（同输入同输出），这是本组唯一不可让的承诺 |
| 在闸门里引入总分 | 契约明令 `score` 不得参与阻断与重跑 |

## 6. 建议排期（一周，3 人）

| 天 | 事项 |
|---|---|
| D1 | 签字（`REVIEW` 三项 + `0.2` 冻结文件）✅ 除 `0.1` 边界外均已记录 |
| D2–D3 | ✅ `6.1` 节点 → `3.3` 报告基线 → `4.x` Issue/Finding 投影 |
| D3–D4 | ✅ `6.2` 阶段目标 + `6.3` 信封；UI 接入（`editor-shell` 按钮改指 `stages/audit`）仍待前端 |
| D4 | ✅ 演示脚本固化（`scripts/audit_demo.py`）+ 性能基准测试锁定 **20 ms** 不回归 |
| D5 | ✅ `DEMO.md` 更新；归档（`/opsx-archive`）待 `0.1` 会签 |

**已完成（本轮）**：O1 性能、O2 冲突检测、O4 向量门禁、O5 摘要必填、规则包体检（`app/rules/doctor.py` + 12 个用例）、
`0.2` 冻结改动 + `3.3` / `4.1`–`4.3` / `6.1`–`6.3`（节点、投影、阶段目标、信封）—— 见 §1、§2.1 第 9–12 行与 §4 第 4 项，
281 个测试全绿。
**仍待口径**：`0.1`（B 会签）、`O3`（B 定闸门语义）、`O6`（C 确认规则包结构）、`O7`（B 定对外文案）。
**仍待别人动手**：`editor-shell` 把"规范审计"按钮从 `stages/normalize` 改指 `stages/audit`（后端已就绪）。