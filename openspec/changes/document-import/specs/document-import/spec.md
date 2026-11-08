# Spec Delta

## Purpose

定义"把客户上传的原始材料变成编辑器里的文本"这一能力：支持 PDF（文本层与扫描件）、DOCX、PNG/JPG，逐文件给出解析结果与失败原因，标记 OCR 来源以便人工核实，并保证导入的不确定性止于冻结快照之前——导入可以不确定，审计仍然只认已确认的值。

## ADDED Requirements

### Requirement: 支持的上传类型与拒绝语义

系统 SHALL 支持 PDF、DOCX、PNG、JPEG 四类原始材料；其他类型 MUST 被明确拒绝并给出原因，MUST NOT 静默当成文本处理，MUST NOT 以空文本冒充成功。

#### Scenario: 上传受支持的类型

- **WHEN** 客户端上传 PDF、DOCX、PNG 或 JPEG
- **THEN** 运行 MUST 记录该文件（`file_id` / `filename` / `mime` / `sha256`）
- **AND** 解析阶段 MUST 为其产出一个 `ParsedDoc`

#### Scenario: 上传不受支持的类型

- **WHEN** 客户端上传例如 `.exe`、`.zip`、`.xlsx`
- **THEN** 该文件的 `ParsedDoc.errors` MUST 含 `unsupported_mime`
- **AND** 其他文件 MUST 继续解析
- **AND** 整次上传 MUST NOT 表现为成功

#### Scenario: 同名重传

- **WHEN** 同一个文件被重复上传
- **THEN** 两次上传 MUST 各自有独立的 `file_id` 与落盘路径
- **AND** 内容相同的文件 MUST 产生相同的 `sha256`

### Requirement: 文本来源必须可识别

每个 `ParsedDoc` SHALL 声明它的文本来源（`form`）：`pdf_text`、`email`、`plain_text`、`docx_text`、`image_ocr`。系统 MUST NOT 把一种来源标成另一种，MUST NOT 让 OCR 文本以 `pdf_text` 或 `plain_text` 出现。

#### Scenario: DOCX 的文本来源

- **WHEN** 一个 `.docx` 文件被解析
- **THEN** 其 `form` MUST 为 `docx_text`

#### Scenario: OCR 的文本来源

- **WHEN** 一个图片或扫描版 PDF 经 OCR 得到文本
- **THEN** 其 `form` MUST 为 `image_ocr`
- **AND** 报告 MUST 让调用方能够据此区分"从文本层读到"与"识别出来的"

#### Scenario: 文本层 PDF

- **WHEN** 一个带文本层的 PDF 被解析
- **THEN** 其 `form` MUST 为 `pdf_text`
- **AND** MUST NOT 对该文件调用 OCR

### Requirement: DOCX 解析只取文本，不执行任何嵌入内容

系统 SHALL 从 DOCX 中提取段落与表格文字（含其原有顺序），MUST NOT 执行宏、嵌入脚本、外部链接或嵌入对象，MUST NOT 依赖办公套件。

#### Scenario: 普通 DOCX

- **WHEN** 一个包含段落与表格的 `.docx` 被解析
- **THEN** `blocks` MUST 按文档顺序包含这些文字
- **AND** `full_text` MUST 与 `blocks` 的顺序一致

#### Scenario: 含宏或嵌入对象的 DOCX

- **WHEN** 文档包含宏、脚本或嵌入对象
- **THEN** 系统 MUST 只处理文字内容
- **AND** MUST NOT 执行或求值任何嵌入内容
- **AND** MUST NOT 因此失败（若正文可抽取）

#### Scenario: 无法解析的 DOCX

- **WHEN** 文件并非有效的 DOCX（例如损坏的压缩包或缺少正文部件）
- **THEN** `errors` MUST 说明原因（例如 `docx_unreadable`）
- **AND** `full_text` MUST 为空且 MUST NOT 被当作成功

### Requirement: 图片与扫描件使用本地 OCR

系统 SHALL 对图片（PNG/JPEG）与**无文本层的 PDF** 使用本地 OCR 引擎识别文字，并为每个文字块保留其在源页/图片上的位置；MUST 使用已安装的本地引擎，MUST NOT 依赖外部模型服务。

#### Scenario: 图片识别成功

- **WHEN** 一张包含文字的图片被解析，且本地 OCR 引擎可用
- **THEN** `blocks` MUST 带上识别出的文字与其在图片上的 `bbox`
- **AND** `full_text` MUST 由这些块按顺序拼接

#### Scenario: 扫描版 PDF

- **WHEN** 一个 PDF 没有文本层
- **THEN** 系统 MUST 对其逐页 OCR，而不是直接判为失败
- **AND** 每个块的 `page` MUST 指向其真实页码

#### Scenario: OCR 引擎不可用

- **WHEN** 本地 OCR 引擎未安装或不可执行
- **THEN** `errors` MUST 含 `ocr_engine_missing`
- **AND** 系统 MUST NOT 崩溃，MUST NOT 返回空的成功结果
- **AND** 用户 MUST 能选择重新上传或从空白继续

### Requirement: 导入失败不伪装成功

系统 SHALL 逐文件记录失败原因，并保证"没读到"与"读到了但内容为空"在数据上可区分；部分失败 MUST 如实反映在阶段报告与本文件中。

#### Scenario: 一张识别不到文字的图片

- **WHEN** OCR 完成但没有任何可用文字
- **THEN** `errors` MUST 含 `no_text_recognized`
- **AND** 该文件 MUST NOT 被宣告为解析成功

#### Scenario: 部分文件失败

- **WHEN** 一次上传中一部分文件成功、一部分失败
- **THEN** 阶段报告 MUST 为 `partial` 并给出原因
- **AND** 成功的文件 MUST 仍然可用
- **AND** 失败的文件 MUST 逐个可指名

#### Scenario: 全部失败

- **WHEN** 一次上传中所有文件都失败
- **THEN** 阶段报告 MUST 为 `failed`
- **AND** 编辑器 MUST 提供"重新上传"或"从空白开始"两条路

### Requirement: 解析结果必须能到达编辑器

系统 SHALL 通过既有的读取入口把每个文档的文本、来源与错误交给客户端；该数据 MUST NOT 只在服务端可见。

#### Scenario: 读取运行的文档

- **WHEN** 客户端读取一个已完成解析的运行
- **THEN** 响应 MUST 包含每个文档的 `file_id`、`filename`、`form`、`errors`、`full_text`
- **AND** 尚未解析的运行 MUST 返回空列表而不是伪造文本

#### Scenario: 把文本填进编辑器

- **WHEN** 客户端拿到解析成功的文档
- **THEN** 它 MUST 能把 `full_text` 作为编辑器初始内容
- **AND** 必须让用户看到该文本的来源（例如"识别自图片"）与失败文件清单

### Requirement: OCR 来源的值不得被当作已确认

系统 SHALL 让 OCR 得到的字段保持未确认状态，直到人工确认；相关检查 MUST NOT 因为"值存在"就算通过。

#### Scenario: 未经确认的 OCR 值参与审计

- **WHEN** 一个来自 OCR 文本的字段尚未人工确认
- **THEN** 依赖它的检查 MUST NOT 为 `pass`
- **AND** 该字段 MUST 在编辑器里标为待核实

#### Scenario: 人工确认之后

- **WHEN** 用户确认或修正了该字段
- **THEN** 值 MUST 带上确认标记与修正后的原文
- **AND** 后续审计 MUST 视为已确认

#### Scenario: 已确认字段不被导入覆盖

- **WHEN** 用户再次上传同一份材料
- **THEN** 已经确认的字段 MUST NOT 被静默覆盖

### Requirement: 导入的边界与规模

系统 SHALL 限制单次导入的规模（页数/字节）并在超限时明确拒绝；MUST NOT 让一次上传无限期占用请求。

#### Scenario: 超出规模上限

- **WHEN** 文件页数或字节数超过配置上限
- **THEN** 系统 MUST 以明确原因拒绝该文件
- **AND** MUST NOT 部分写入后又宣告成功

#### Scenario: 一次一个文档进编辑器

- **WHEN** 用户一次选择多个文件
- **THEN** 系统 MUST 逐个解析并逐个报告
- **AND** 编辑器 MUST 只接收一个文档的文本作为初始内容（由用户选择哪一个）