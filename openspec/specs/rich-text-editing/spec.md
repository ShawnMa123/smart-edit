# rich-text-editing Specification

## Purpose
定义"富文本文档的编辑与呈现"这一能力：把编辑器从纯文本升级为可渲染的结构化文档（ED-02 的段落、标题、粗斜体下划线、列表、表格、撤销重做、查找替换、工具栏与选区同步），并用一条**确定性的纯文本投影**把富文档与审计输入绑在一起，使"看得见格式"不再以牺牲审计确定性为代价。

## Requirements

### Requirement: 编辑器支持 ED-02 的格式集合

编辑器 SHALL 支持段落、标题（至少三级）、粗体、斜体、下划线、有序列表、无序列表与表格；用户 MUST 能用工具栏或键盘快捷键施加与取消这些格式。

#### Scenario: 施加与取消标记
- **WHEN** 用户选中一段文字并点击"粗体"
- **THEN** 该段文字 MUST 显示为粗体
- **AND** 再次点击同一按钮 MUST 取消粗体并恢复原样

#### Scenario: 标题层级
- **WHEN** 用户把某一段落设为二级标题
- **THEN** 该段落 MUST 以标题样式呈现
- **AND** 其纯文本投影 MUST 以对应数量的 `#` 开头（见"投影"要求）

#### Scenario: 表格的增删行与列
- **WHEN** 光标位于表格中
- **THEN** 用户 MUST 能在当前行之前/之后插入行、删除当前行、在列之前/之后插入列、删除当前列
- **AND** 表头行 MUST 可以被标记

#### Scenario: 撤销与重做
- **WHEN** 用户连续编辑后执行撤销
- **THEN** 文档 MUST 回到上一个编辑状态
- **AND** 重做 MUST 能恢复被撤销的编辑

#### Scenario: 查找与替换
- **WHEN** 用户在查找框输入文本
- **THEN** 匹配项 MUST 被定位并可逐个跳转
- **AND** 替换单个或全部 MUST 只修改命中的文字，MUST NOT 破坏其所在的格式结构

### Requirement: 工具栏状态与当前选区一致

工具栏 SHALL 反映光标或选区当前的格式状态；MUST NOT 显示"已启用"而实际未作用于选区。

#### Scenario: 光标落在粗体文字内
- **WHEN** 光标位于一段粗体文字中
- **THEN** 粗体按钮 MUST 显示为激活
- **AND** 光标移出该段后 MUST 恢复未激活

#### Scenario: 混合选区
- **WHEN** 选区同时包含粗体与非粗体文字
- **THEN** 工具栏 MUST NOT 把该标记显示为"完全启用"

### Requirement: 富文档必须有确定性的纯文本投影

系统 SHALL 提供一个纯函数 `richToPlainText`，把富文档投影为审计使用的纯文本；同一份富文档 MUST 每次投影出完全相同的结果，且该结果 MUST 是提交给审计的唯一文本。

#### Scenario: 投影规则
- **WHEN** 文档包含标题、列表与表格
- **THEN** 标题 MUST 投影为 `#`／`##`／`###` 加空格前缀
- **AND** 无序列表项 MUST 以 `- ` 开头，有序列表项 MUST 以 `1. ` 这类编号开头
- **AND** 表格 MUST 每行一条，单元格之间用 ` | ` 分隔
- **AND** 段落之间 MUST 以单个空行分隔

#### Scenario: 同一文档两次投影一致
- **WHEN** 同一份富文档被投影两次（含撤销/重做之后回到同一状态）
- **THEN** 两次结果 MUST 完全相同

#### Scenario: 空文档
- **WHEN** 编辑器为空
- **THEN** 投影结果 MUST 为空字符串
- **AND** 提交审计时 MUST 按"空提交"处理，MUST NOT 伪造一份文本

### Requirement: 审计只读投影文本，且行为与改造前一致

审计输入 SHALL 是投影文本；既有"粘贴纯文本 → 标准化 → 审计"的结果 MUST 与改造前一致，即便编辑器换了实现。

#### Scenario: 纯文本内容
- **WHEN** 用户把一段纯文本粘贴进富文本编辑器（无任何标记）
- **THEN** 投影文本 MUST 与粘贴的内容一致（除段落分隔的空行）
- **AND** 由此得到的字段、快照摘要与审计结论 MUST 与改造前相同

#### Scenario: 富文本不会让审计"看不见"
- **WHEN** 文本带有标题、列表或表格格式
- **THEN** 审计 MUST 收到包含这些结构标记的投影文本
- **AND** MUST NOT 因格式而丢弃正文内容

#### Scenario: 快照与版本绑定投影
- **WHEN** 用户捕获一个版本
- **THEN** 版本 MUST 同时保存富文档与当时的投影文本
- **AND** 重新审计该版本 MUST 使用该版本保存的投影文本

### Requirement: 导入结果成为富文档，并标明推断方式

解析结果 SHALL 以富结构提供给编辑器：DOCX 按 OOXML 结构确定性映射，PDF 依据字号与位置做启发式推断；每条推断 MUST 标注其来源（`deterministic` / `heuristic` / `fallback`），MUST NOT 把推断冒充为文档中的事实。

#### Scenario: DOCX 的确定性映射
- **WHEN** 一个 DOCX 含标题样式、粗体与表格
- **THEN** 富文档 MUST 呈现对应级别的标题、粗体与表格
- **AND** 每一处映射 MUST 标注为 `deterministic`

#### Scenario: PDF 的启发式推断
- **WHEN** 一个 PDF 中某块字号显著大于正文
- **THEN** 系统 MAY 把它推断为标题
- **AND** 该推断 MUST 标注为 `heuristic`
- **AND** MUST NOT 因推断而改变该块的文字内容

#### Scenario: 无法判断时退化为段落
- **WHEN** 版式信息不足（例如纯文本粘贴、OCR 文本无字号）
- **THEN** 所有块 MUST 退化为普通段落
- **AND** MUST NOT 猜测标题级别
- **AND** 标注 MUST 为 `fallback`

#### Scenario: 转换失败不阻断导入
- **WHEN** 富结构转换出错
- **THEN** 导入 MUST 仍然成功并给出纯文本（旧行为）
- **AND** 该文档的富结构 MUST 标注为 `fallback`，且 MUST NOT 报告为已还原格式

### Requirement: 富文档只在浏览器，接口只做加法

富文档 SHALL 仅存在于客户端（本构建无数据库）；服务端 MUST 继续只接收与返回纯文本，除新增可选的 `documents[].rich` 外 MUST NOT 改变既有契约。

#### Scenario: 提交审计
- **WHEN** 前端发起一次审计
- **THEN** 请求体 MUST 只包含投影文本（与改造前相同）
- **AND** MUST NOT 因富文档而改变 `POST /runs` 或阶段接口的语义

#### Scenario: 读取解析结果
- **WHEN** 客户端读取已完成解析的运行
- **THEN** `documents[]` MAY 携带 `rich` 结构
- **AND** 缺少 `rich` 时客户端 MUST 退化为把 `full_text` 当作纯文本文档（旧行为）

### Requirement: 格式能力不得削弱既有的诚实性约束

引入富文本 SHALL NOT 削弱既有约束：找不到证据的值不得因格式而算通过、OCR 文本仍然待核实、空结果不得伪装成功。

#### Scenario: 格式不改变判定
- **WHEN** 同一份文本仅改变其格式（例如把金额加粗或设为标题）
- **THEN** 审计的字段状态与结论 MUST 不变
- **AND** 仅标记结构变化引起的投影差异不得造成新的 finding

#### Scenario: OCR 文本仍待核实
- **WHEN** 导入的文本来自 OCR
- **THEN** 其在富文档中 MAY 被格式化
- **AND** 由它抽取的字段 MUST 仍为待人工确认，MUST NOT 因为"看起来整齐"而被视为已确认

### Requirement: 富文档可携带显示属性与页边界

编辑器 SHALL 支持段落与标题上的可选显示属性（`fontSize` / `fontFamily` / `page`）以及不产生文字的分页标记（`pageBreak`）。显示属性与分页标记 MUST 只影响呈现，MUST NOT 参与纯文本投影；缺少这些属性或标记的既有富文档 MUST 仍能正常渲染。

#### Scenario: 显示属性只影响呈现
- **WHEN** 一个标题带有 `fontSize: 20`、`fontFamily: Arial` 与 `page: 3`
- **THEN** 编辑器 MUST 按该字号与字体呈现它
- **AND** 其纯文本投影 MUST 与去掉这三个属性时完全相同

#### Scenario: 页边界可见但不产生文字
- **WHEN** 富文档含有 `pageBreak` 标记
- **THEN** 编辑器 MUST 显示一条可见的分隔（而不是空白）
- **AND** 纯文本投影 MUST NOT 因该标记增加任何字符
- **AND** 用户 MUST 可以在编辑器中删除该标记

#### Scenario: 旧文档兼容
- **WHEN** 打开一份不含任何显示属性与 `pageBreak` 的富文档
- **THEN** 编辑器 MUST 正常渲染该文档
- **AND** 其投影 MUST 与本次扩展前完全一致
