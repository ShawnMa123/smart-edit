# Eval Benchmark

## Purpose

本 capability 定义**离线评测**的格式与口径。它与 Agent 4（`output-verification`）不是一回事：

| | 离线 Benchmark（本 capability） | 在线校验（`output-verification`） |
|---|---|---|
| 在哪跑 | 开发机 | 运行路径上 |
| 有无真值 | **有**（gold） | 无 |
| 判什么 | 抽得对不对、报得全不全 | 证据链是否自洽 |
| 能否阻断 | 否 | 是 |

**MUST NOT 混用**：不能用 benchmark 口径做运行时阻断（线上没有真值），
也不能用在线校验结果代替质量评估（它不判断对错）。

## ADDED Requirements

### Requirement: 分层评测

系统 SHALL 按层评测，每层有独立真值与指标。

#### Scenario: POC 只做四层
- **WHEN** 运行评测
- **THEN** MUST 覆盖 L1（字段抽取）、L2（要件规则）、L3（RAG）、L5（端到端）
- **AND** MUST NOT 实现 L4（LLM-as-judge）

#### Scenario: 各层的真值来源
- **WHEN** 评测某一层
- **THEN** L1 用 `eval/gold/`，L2 用 `eval/gold_rules/`，L3 用 `eval/gold_retrieval.json`，
  L5 用人工基线
- **AND** 每一层的数字 MUST 能追溯到具体样本

### Requirement: L1 字段真值格式

系统 SHALL 以统一格式记录字段抽取的真值。

#### Scenario: 单样本 gold 文件
- **WHEN** 标注一份样本的字段真值
- **THEN** 文件 MUST 位于 `eval/gold/<sample_id>.json`，含：

```json
{
  "sample_id": "S01",
  "files": ["invoice.pdf"],
  "business_type": "guarantee",
  "fields": {
    "applicant_name":    {"value": "ABC TRADING PTE LTD", "tolerance": "exact"},
    "amount":            {"value": "500000.00",           "tolerance": "numeric"},
    "expiry_date":       {"value": "2026-12-31",          "tolerance": "date"},
    "goods_description": {"value": "ELECTRONIC COMPONENTS", "tolerance": "fuzzy:0.85"}
  }
}
```

#### Scenario: tolerance 的取值与比对方式
- **WHEN** 比对预估值与 gold
- **THEN** 比对方式 MUST 由 `tolerance` 决定：

| tolerance | 比法 |
|---|---|
| `exact` | 归一化后（去首尾空格、转大写）全等 |
| `numeric` | 转 `Decimal` 后相等 |
| `date` | 转 ISO 日期后相等 |
| `fuzzy:<阈值>` | 相似度 ≥ 阈值（默认 0.85） |

- **AND** 未声明 `tolerance` 的字段 MUST 视为 `exact`

#### Scenario: files 的取值
- **WHEN** 填写 `files`
- **THEN** MUST 只包含 POC 支持的格式（文本型 PDF、粘贴文本、纯文本邮件）
- **AND** MUST NOT 包含 Word、Excel 或扫描件

### Requirement: L1 指标

系统 SHALL 按字段类型分别报告指标，MUST NOT 只报总平均。

#### Scenario: 分类型报告
- **WHEN** 计算 L1 指标
- **THEN** MUST 按字段类型（金额 / 日期 / 名称 / 描述等）分别给出 P / R / F1
- **AND** MUST NOT 只给出一个总体平均分
- **理由**：总平均会掩盖"金额 1.00、描述 0.68"这种关键差异

#### Scenario: 业务方可读的两个数
- **WHEN** 报告 L1 结果
- **THEN** MUST 额外给出：
  - **整份零错误率** = 完全无错的样本数 / 总样本数
  - **推断率** = `inferred` 字段数 / 总字段数（越低越好，但 MUST NOT 为 0）

#### Scenario: 出处准确率抽检
- **WHEN** 报告出处准确率
- **THEN** MUST 从 `extracted` 字段中随机抽 30 个，人工确认 `source.span` 是否真在原文对应位置
- **AND** MUST NOT 用程序自动统计代替这一步

### Requirement: L2 规则真值格式

系统 SHALL 以统一格式记录"应报哪些 Finding"。

#### Scenario: 单样本 gold_rules 文件
- **WHEN** 标注一份样本的应报清单
- **THEN** 文件 MUST 位于 `eval/gold_rules/<sample_id>.json`，每个条目含：

```json
[
  {
    "kind": "missing",
    "rule_id": "REQ-DOC-002",
    "severity": "critical",
    "blocking": true,
    "field_keys": ["application_form"],
    "note": "保函申请书确实未提交"
  }
]
```

#### Scenario: 标注口径
- **WHEN** 标注 `gold_rules`
- **THEN** MUST 只标"业务上应该报什么"
- **AND** MUST NOT 参考模型实际报了什么

#### Scenario: 分歧处理
- **WHEN** 两人对同一处是否应报存在分歧
- **THEN** MUST 各标一半再交叉复核
- **AND** MUST NOT 由单人决定

#### Scenario: L2 指标
- **WHEN** 计算 L2 指标
- **THEN** MUST 报告 **blocking 漏报数**（最关键的指标）
- **AND** SHOULD 报告误报数

### Requirement: L3 检索与引用真值

系统 SHALL 记录检索与引用的真值，用于评估 RAG 质量。

#### Scenario: 检索真值
- **WHEN** 构造 `eval/gold_retrieval.json`
- **THEN** MUST 含 20 个问题，每题列出应命中的 `chunk_id`
- **AND** 指标 MUST 为 **Recall@5**（应命中 chunk 是否在前 5）与 **MRR**（首个正确 chunk 的排名倒数）

#### Scenario: 引用支持度抽检
- **WHEN** 评估引用质量
- **THEN** MUST 抽 50 条 claim 人工判定，结果写入 `eval/citations_50.csv`
- **AND** 每条判定 MUST 为 `supported` / `partial` / `unsupported` 之一：

| 判定 | 含义 |
|---|---|
| `supported` | 引用片段确实支持这句话 |
| `partial` | 部分支持（数值对、条件缺） |
| `unsupported` | 不支持或无关 |

- **AND** 指标 MUST 为 `citation_support_rate = supported / 50` 与 `partial_support_rate = partial / 50`

#### Scenario: 拒答率
- **WHEN** 评估覆盖声明
- **THEN** MUST 构造 10 个超出语料覆盖范围的问题，检查是否输出 `coverage.unavailable`
- **AND** 指标 MUST 为 `refusal_rate = 正确拒答数 / 10`，目标 ≥ 0.9
- **理由**：这一项最能体现"没检索到 ≠ 没问题"的设计意图

### Requirement: L5 端到端指标

系统 SHALL 以人工基线衡量端到端价值。

#### Scenario: 必测四项
- **WHEN** 做端到端评测
- **THEN** MUST 测：人工修改字段数、单份处理时间、纯人工基线时间、提升倍数

#### Scenario: 报告口径
- **WHEN** 对外报告端到端结果
- **THEN** MUST 使用固定句式，形如：
  "N 份样本，纯人工平均 X 分钟，使用后平均 Y 分钟，AI 生成后平均修改 Z 个字段。"

### Requirement: 报告范围

系统 SHALL 明确报什么、不报什么。

#### Scenario: 必须报
- **WHEN** 产出 `eval/report.md`
- **THEN** MUST 包含：整份零错误率、字段 F1（按类型拆）、blocking 漏报数、
  citation support rate、端到端时间与修改字段数

#### Scenario: 不得报
- **WHEN** 产出报告
- **THEN** MUST NOT 包含：单一综合分数、LLM-as-judge 打分、与其他框架的横向对比

#### Scenario: 必须主动声明的限制
- **WHEN** 交付报告
- **THEN** MUST 声明：
  - 语料规模为 POC 级（20 条），未做 rerank
  - `citation_check` 只做实体覆盖，未做语义蕴含
  - 样本量小，F1 置信区间约 ±5 个点

### Requirement: 评测目录结构

系统 SHALL 以固定目录组织评测资产。

#### Scenario: 目录布局
- **WHEN** 建立评测资产
- **THEN** MUST 为：

```text
eval/
  gold/                  # L1 真值（B 主标）
  gold_rules/            # L2 真值（B 主标）
  gold_retrieval.json    # L3 检索真值（C 标）
  citations_50.csv       # L3 引用抽检（C 标）
  samples/               # 原始样本（脱敏，不入库）
  run_eval.py            # 一键跑 L1/L2/L3
  report.md              # 输出结果，交付时附上
```

#### Scenario: 样本不入库
- **WHEN** 提交代码
- **THEN** `eval/samples/` MUST 被 `.gitignore` 排除
- **AND** gold 文件 MUST 入库（它们是脱敏后的真值，不含原文）

### Requirement: 可复算

系统 SHALL 保证报告中的每个数字都能复算。

#### Scenario: 数字可追溯
- **WHEN** 报告中出现一个指标值
- **THEN** MUST 能定位到计算它的具体样本与代码路径

#### Scenario: 一键重跑
- **WHEN** 修改了 prompt、规则或语料
- **THEN** `run_eval.py` MUST 能一键重跑 L1/L2/L3 并输出 markdown 表

#### Scenario: 禁止手改报告
- **WHEN** 更新 `eval/report.md`
- **THEN** MUST 由 `run_eval.py` 生成或更新对应数字
- **AND** MUST NOT 手工填写未经计算的数值
