# Normalization

## Purpose

本 capability 定义 Agent 1 从客户原始材料到结构化字段的转换口径：**只改形式不改事实** ——
值保留原文大小写与拼写、出处是最小可定位片段、无法确定的必须降级为 `inferred` 或 `missing`，
且每次对原文的操作都必须留痕。范围不含 OCR、扫描件与表单结构还原；
`parse` / `extract` / `normalize` 的实现属 `poc-skeleton` 的共享层，本 capability 只约束其行为。

## ADDED Requirements

### Requirement: 解析必须保留原文结构

系统 SHALL 将输入文件解析为按序的文本块，并保留可定位信息。

#### Scenario: 文本型 PDF
- **WHEN** 解析一份有文本层的 PDF
- **THEN** 每个 `ParsedBlock` MUST 含 `file_id`、`page`、`bbox`、`text`
- **AND** `text` MUST 与原文逐字一致，不得折叠空白、不得改写

#### Scenario: 无位置的输入
- **WHEN** 输入为粘贴文本或纯文本邮件
- **THEN** `page` 与 `bbox` MUST 为 `null`，`text` 仍 MUST 与原文逐字一致

#### Scenario: 扫描件不得伪装成功
- **WHEN** PDF 无文本层（疑为扫描件）
- **THEN** 系统 MUST 记录明确错误并说明"扫描件不支持"
- **AND** MUST NOT 返回空字符串或空 `full_text` 作为解析成功

#### Scenario: 部分文件失败
- **WHEN** 多个文件中有部分解析失败
- **THEN** 失败项 MUST 记入 `ParsedDoc.errors`，其余文件 MUST 继续处理

#### Scenario: 全部文件失败
- **WHEN** 所有文件均解析失败
- **THEN** `fields` MUST 为空，`StageReport.status` MUST 为 `failed`，整次运行 MUST 判定为 `fail`

### Requirement: 字段抽取必须绑定出处

系统 SHALL 为每个抽取出的字段记录其在原始文件中的位置。

#### Scenario: 抽取值带出处
- **WHEN** 从文本型 PDF 中抽取到金额字段
- **THEN** `source` MUST 含 `file_id`、`page`、`bbox` 与该值所在的原始片段 `span`

#### Scenario: span 是片段而非整行
- **WHEN** 原文写作 `申请人：ABC TRADING PTE LTD 地址：新加坡`
- **THEN** `span` MUST 为 `ABC TRADING PTE LTD`，MUST NOT 包含 `申请人：` 等栏目标签与相邻字段

#### Scenario: 无法定位时不得声称已定位
- **WHEN** 模型给出的值在原文中找不到对应片段
- **THEN** 该字段 `status` MUST 为 `inferred`，`source` MUST 为 `null`

#### Scenario: 出处必须能跳回具体页
- **WHEN** 输入为文本型 PDF 且该字段被标为 `extracted`
- **THEN** `source.page` MUST 为该片段所在的页码，MUST NOT 恒为 `null`
- **AND** 页码 MUST 由系统在 `ParsedBlock` 上回查得到，MUST NOT 由模型直接产出

#### Scenario: 不得跨文件定位
- **WHEN** 某字段的 `span` 在它自己声明的 `source.file_id` 中找不到，但在另一份文件中能找到
- **THEN** 该字段 MUST 判为 `inferred`
- **AND** MUST NOT 因"别的文件里有这段文字"而保留 `extracted`

#### Scenario: 跨页拼接必须降级
- **WHEN** 一个值的片段跨越两页
- **THEN** 系统 MUST 在 `notes` 写入 `merged_across_pages`、记为 `op="transform"` 且 `detail.cross_page=true`
- **AND** `status` MUST 降为 `inferred`，因为跨页拼接改变了排版事实，需人工确认

#### Scenario: 原文中的字段称呼
- **WHEN** 原文对该字段有明确称呼（如"保函金额"）
- **THEN** `FieldValue.label` MUST 记录该称呼，供核对台展示

### Requirement: 三分类判定

系统 SHALL 将每个字段标记为 `extracted`、`inferred`、`missing` 之一。

#### Scenario: extracted 判定
- **WHEN** 字段值可由原文片段经规范化得到，且该片段能在原文中定位
- **THEN** `status` MUST 为 `extracted`

#### Scenario: 定位前的归一化
- **WHEN** 判断 `span` 是否能在原文中定位
- **THEN** 系统 MUST 先按共享层的 5 步规则归一化（NFKC 全半角 → 剔除零宽字符 → 连字符归一 → 引号归一 → 空白折叠）后再比对
- **AND** MUST NOT 因空白、全半角、连字符或引号差异把本可定位的字段判为 `inferred`
- **AND** MUST NOT 折叠大小写 —— 大小写差异意味着模型没有逐字复制，正应判为不可定位

#### Scenario: 片段上限
- **WHEN** 模型给出的 `span` 长度超过共享层常量 `MAX_SPAN_LEN`（200）
- **THEN** 系统 MUST 先按句末标点切到上限内
- **AND** 若切不出（单句超上限），MUST 在 `notes` 写入 `span_oversize` 并把 `status` 降为 `inferred`
- **AND** MUST NOT 截断 `span` 本体（截断会让出处校验直接失败）

#### Scenario: inferred 判定
- **WHEN** 字段值来自模型推理，原文无直接对应片段
- **THEN** `status` MUST 为 `inferred`，`confirmed` MUST 为 `false`

#### Scenario: missing 判定
- **WHEN** 原文既无该值也无法推理
- **THEN** `status` MUST 为 `missing`，`value` MUST 为 `null`

#### Scenario: 必填字段缺候选时必须有占位
- **WHEN** `fields.yaml` 中某字段 `required` 为 `true`，但抽取结果里没有任何候选
- **THEN** `fields` MUST 存在该键，且 `status="missing"`、`value=null`、`notes` 含 `not_in_source`
- **AND** MUST 写一条 `op="pass"` 的 `TrailEntry` 说明"原文未出现该字段"
- **AND** MUST NOT 让该键在 `fields` 中缺席 —— 缺席会让下游无法区分"原文没写"与"没抽出来"
- **AND** MUST NOT 因此产出 `Finding`（是否阻断由 Agent 2 判定）

#### Scenario: 可选字段缺失不占位
- **WHEN** `required` 为 `false`（或未声明）的字段没有候选
- **THEN** 该键 MUST NOT 出现在 `fields` 中

#### Scenario: 降级说明必须影响判定
- **WHEN** 某字段带 `date_ambiguous` / `amount_not_numeric` / `currency_not_iso4217` / `value_truncated` / `span_oversize` / `merged_across_pages` 任一说明
- **THEN** `status` MUST 为 `inferred`，MUST NOT 为 `extracted`

#### Scenario: inferred 的人工确认
- **WHEN** 用户在核对台确认了一个 `inferred` 字段
- **THEN** `confirmed` MUST 置为 `true`，`status` MUST NOT 被改写
- **AND** 是否阻止导出 MUST 由闸门依据 `confirmed` 判定，不得依赖 `status` 变化

### Requirement: 只改形式不改事实

系统 MUST NOT 修改、补全、概括或改写原文表达的事实内容。

#### Scenario: 值规范化
- **WHEN** 原文金额写作 `USD 500K`
- **THEN** 系统 MAY 规范化为 `500000.00`，但 MUST 在 `normalized_from` 保留原值 `USD 500K`

#### Scenario: 名称不得改变大小写与拼写
- **WHEN** 原文写作 `ABC Trading Pte Ltd`
- **THEN** `value` MUST 保持 `ABC Trading Pte Ltd`，MUST NOT 转成大写或纠正拼写

#### Scenario: 模糊表述不得被确定化
- **WHEN** 原文写作"金额大概 50 万美金"
- **THEN** 抽取值 MUST 标记 `inferred`，MUST NOT 直接当作 `500000.00 USD` 的确定值

#### Scenario: 主体名称不得补全
- **WHEN** 原文写作"新加坡那个公司"
- **THEN** 系统 MUST 保留原文表述并标记 `inferred`，MUST NOT 补成任何具体公司名

#### Scenario: 不得概括
- **WHEN** 原文为长段落条款
- **THEN** 系统 MUST NOT 产出该段落的摘要作为字段值，MUST NOT 用模型生成的转述替代原文

### Requirement: 自由操作必须留痕

系统 SHALL 记录对原文的每一次读取、模型调用、转换与放行。

#### Scenario: 每字段可追溯
- **WHEN** 产出任一字段
- **THEN** MUST 存在至少一条 `TrailEntry`，其 `after` 为该值、`before` 为原文片段

#### Scenario: 越界操作必须记录为越界
- **WHEN** 系统对原文执行了概括、改写或丢弃
- **THEN** `TrailEntry.op` MUST 记为 `summarize` / `rewrite` / `drop`

#### Scenario: 范围性跳过不等于越界
- **WHEN** 因相关性过滤未处理部分页面
- **THEN** MUST 记为 `op="pass"` 并在 `detail` 说明理由，MUST NOT 静默跳过

#### Scenario: 长文档分批抽取
- **WHEN** 单份文档超过模型上下文预算
- **THEN** 系统 MUST 分批抽取，且每批 MUST 各自写明处理范围

### Requirement: 字段字典映射

系统 SHALL 依据 `fields.yaml` 将抽取值映射到系统字段名，并区分规范化职责与校验职责。

#### Scenario: 职责分离
- **WHEN** `fields.yaml` 声明某字段的约束
- **THEN** 每条约束 MUST 标注归属 `stage`（`normalize` 归本 Agent，`validate` 归 Agent 2）
- **AND** 本 Agent MUST NOT 执行 `stage=validate` 的约束
- **AND** `max_length` / `charset` / `precision` / `thousands` / `date_order` MUST 归 `stage.normalize`
- **AND** `required` MUST 归 `stage.validate`，本 Agent 只**读取**它决定是否补 `missing` 占位，MUST NOT 据此判定阻断

#### Scenario: 字段字典不可用
- **WHEN** `fields.yaml` 缺失或无法解析
- **THEN** 三个阶段 MUST 全部 `status="failed"`，整次运行判 `fail`
- **AND** MUST NOT 用空字典继续执行（否则全部字段会静默进 `extra_fields`，把配置事故伪装成"材料没写"）

#### Scenario: 字段长度超限
- **WHEN** 某字段值超过 `fields.yaml` 声明的 `max_length`
- **THEN** 系统 MUST 截断、写入 `notes` 含 `value_truncated`、把 `status` 降为 `inferred`，并产生一条 `severity="warn"` 的 Finding（`source="normalization"`, `kind="invalid_value"`, `blocking=false`）
- **AND** MUST NOT 静默丢弃
- **AND** 该 Finding 的 `id` MUST 由节点统一分配（`N-` 前缀，agent 内自增），MUST NOT 由纯函数自行编号
- **AND** 重跑后新 Finding 的 `id` MUST NOT 与已有条目撞号

#### Scenario: 未在字典中的字段
- **WHEN** 抽取出 `fields.yaml` 未定义的字段
- **THEN** 系统 MUST 将其放入 `extra_fields`，MUST NOT 混入 `fields`

#### Scenario: 日期歧义
- **WHEN** 日期形如 `12/03/26` 且字段未声明 `date_order`
- **THEN** 系统 MUST 在 `notes` 写入 `date_ambiguous` 并降为 `inferred`
- **AND** MUST NOT 任选一种解释当作确定值

### Requirement: 业务类型判定

系统 SHALL 判断材料所属业务类型并写入 `business_type`。

#### Scenario: 有明确依据
- **WHEN** 文档中出现 `GUARANTEE` / `保函` / `URDG 758` 等明确标识
- **THEN** `business_type` MUST 为 `guarantee`，并 MUST 在 trail 中记录依据原文

#### Scenario: 无依据时不得臆断
- **WHEN** 材料不足以判定业务类型，或类型不在 POC 支持范围内
- **THEN** `business_type` MUST 为 `unsupported`
- **AND** MUST NOT 为保证下游可运行而强行赋予某个类型

#### Scenario: 唯一写入者
- **WHEN** 需要写入 `EditState.business_type`
- **THEN** MUST 只由 `normalize` 阶段写入
- **AND** `ingest` MUST 只透传已有值，MUST NOT 自行判定
- **AND** Agent 3 在 `raw` 模式推断出的类型 MUST 只写入 `legal.coverage`

#### Scenario: 判定依据必须留痕
- **WHEN** 产出一个 `business_type`（含 `unsupported`）
- **THEN** MUST 写一条 `op="pass"` 的 `TrailEntry`，`detail` 含 `business_type` / `evidence` / `reason`
- **AND** `unsupported` 分支的 `reason` MUST 区分"类型不支持"与"无依据"

### Requirement: 阶段可独立触发

系统 SHALL 允许只运行 Agent 1 的部分阶段。

#### Scenario: 只解析
- **WHEN** 调用方只请求 `parse`
- **THEN** 系统 MUST 只产出 `docs`，MUST NOT 产出 `fields`

#### Scenario: 解析加抽取
- **WHEN** 调用方请求 `parse → extract`
- **THEN** 系统 MUST 产出 `docs` 与候选字段
- **AND** MUST NOT 写入 `fields`，因为候选值尚未经过规范化与三分类判定

#### Scenario: 解析行为一致
- **WHEN** 同一文件分别经完整流程与独立触发被解析
- **THEN** 两次的 `ParsedDoc.blocks` MUST 逐块一致

#### Scenario: 三档触发必须已登记
- **WHEN** 调用方请求 `stages=parse` / `stages=extract` / `stages=normalize`
- **THEN** 三个取值 MUST 都登记为编排层的 stage target
- **AND** 未登记的目标 MUST 被拒绝（`409`），MUST NOT 静默降级为"跑完整链"

### Requirement: 归一化基准全层唯一

系统 SHALL 用同一份实现判断"两个字符串是否指向同一段原文"。

#### Scenario: 规则清单固定
- **WHEN** 实现 `normalize_ws`
- **THEN** MUST 按固定顺序执行五步：NFKC 兼容归一 → 剔除零宽与方向控制字符 → 连字符归一 → 引号归一 → 空白折叠
- **AND** MUST NOT 折叠大小写、去标点、做同义词或单位换算

#### Scenario: 不得私有实现
- **WHEN** Agent 1 判定 `extracted`、Agent 4 校验出处
- **THEN** 两处 MUST 调用共享层同一个函数
- **AND** MUST NOT 各自实现一份（分叉会导致全部字段被误判为不合规）

#### Scenario: 片段上限共用常量
- **WHEN** 判定 `span` 是否过长
- **THEN** MUST 使用共享层常量 `MAX_SPAN_LEN`，不得各写一个数

### Requirement: Agent 1 的 Finding 边界

系统 SHALL 明确 Agent 1 产出 Finding 的范围与形态。

#### Scenario: 只产 invalid_value
- **WHEN** Agent 1 产出 Finding
- **THEN** `source` MUST 为 `normalization`，`id` 前缀 MUST 为 `N-`
- **AND** `kind` MUST 为 `invalid_value`（值超长被截断等）
- **AND** MUST NOT 产出 `missing` / `inconsistent` / `policy_violation` 类结论（那是 Agent 2/3 的判定）

#### Scenario: 初始状态不可自定
- **WHEN** Agent 1 产出一条 Finding
- **THEN** `resolved` MUST 为 `false`、`resolution` MUST 为 `null`、`blocking` MUST 为 `false`
- **AND** `blocking` MUST NOT 由 Agent 1 声明，MUST 由 `requirements.yaml` 的规则决定
