# Proposal

## Why

知识问答面板现在有 **5 个输入点**（问题框、联网开关、法域下拉、交易日、规则版本）。后三个是上一轮为"精确检索"加的，但实测收益递减：`As of` 只影响时效过滤、`Rule` 只免一次澄清，而用户最需要的是"问一句话就能答"。

更关键的是**默认值选择错了**：联网必须手动勾选，于是绝大多数提问不会联网。实测同一条法规类问题，不勾选时直接停在 `insufficient_evidence`，用户看到"没有可发布的结论"，而不是"我给你搜了一下公开来源"。

另外，出站脱敏的 6 条正则**写死在代码里**，`app/configs/egress.yaml` 只能调域名、长度与自由词。客户或赛题想换预设（例如增加"合同编号"格式）只能改代码，而这恰恰是"用户输入敏感信息校验"最需要可配置的部分。

## What Changes

- **UI 简化**：删掉 `As of (trade date)` 与 `Rule (applicability only)` 两个文本输入；法域从下拉改为**一行 chips**（选项来自配置预设）；联网开关变为**默认开启、可手动关闭**，并保留一行常驻说明。
- **默认值落在部署层**：新增 `SMART_EDIT_ASSISTANT_WEB_DEFAULT`（默认 `on`），通过能力自检响应暴露给前端；前端不硬编码策略。用户手动切换后以用户选择为准。
- **每次运行仍然显式发送** `web_search`，并在运行审计里记录 `web_source`（`user` / `default`），使"这次到底有没有外呼、是谁决定的"可自证。
- **敏感信息预设配置化**：新增 `app/configs/knowledge.sample.json`，把出站脱敏规则（金额、单号、长数字、邮箱、URL、变量占位）、准入域名、查询长度上限、法域预设与示例问题集中为**数据**；加载器支持 JSON 并保留 `egress.yaml` 兼容。
- **配置化的四条护栏**：文件缺失或损坏 → 拒绝一切外呼；正则编译失败 → 启动失败；**规则编号豁免（URDG/UCP/ISP… 必须存活）不可配置**；规则条数与模式长度有上限（防灾难性回溯）。
- **规范处理**：新增能力 `knowledge-web-fallback-policy` 拥有"默认开启 + 可显式关闭 + 必须可审计"的行为；本 change 在 proposal 中**声明取代** `knowledge-retrieval-layers` 与 `knowledge-general-web` 中"默认不联网、必须显式开启"的默认值条款（见 Impact 与 Open Questions）。

**Out of scope（本 change 不做）**：多法域同时选择；把规则版本作为第二路检索串；用户选择在会话/浏览器间持久化；People/组织级默认策略；修改那两个历史 change 的规范文件本身。

## Capabilities

### New Capabilities

- `knowledge-web-fallback-policy`: 联网兜底的策略归属——默认值由谁决定、用户如何关闭、每次运行如何记录有效选择与来源、外呼前必须经过什么校验，以及联网结果如何标注。

### Modified Capabilities

<!-- 无：`knowledge-retrieval-layers` 与 `knowledge-general-web` 都还只在未归档的 change 里，`openspec/specs/` 下没有对应能力，无法写 MODIFIED delta。默认值条款的取代关系写在本 proposal 与 Open Questions 中。 -->

## Impact

- **前端**：`web/src/components/KnowledgePanel.tsx`（删两个字段、法域改 chips、开关初值来自能力、常驻说明）、`web/src/api/assistantTypes.ts`（`web.default_on`、法域预设）、组件测试与 `web/e2e/*`。
- **后端**：`app/assistant/settings.py`（`SMART_EDIT_ASSISTANT_WEB_DEFAULT`、配置路径）、`app/assistant/schemas.py`（`WebCapability.default_on`、能力里的预设清单）、`app/assistant/service.py`（能力填充、运行审计 `web_source`）、`app/assistant/egress.py`（从 JSON 读取并编译规则、护栏）。
- **配置**：新增 `app/configs/knowledge.sample.json`；`app/configs/egress.yaml` 继续可用（优先级：显式配置路径 > knowledge.json > egress.yaml）。
- **规范**：`knowledge-retrieval-layers`（默认不联网/显式开启）与 `knowledge-general-web`（通用通道启用条件）两条要求的默认值语义被本 change 取代；两者归档时需按其 owner 的流程更新。
- **行为影响（需要知情）**：默认开启意味着**用户无需操作，问题就可能被送到公开检索**；外呼次数与"问题被标记为已脱敏"的频率都会上升。答案中已有的 unverified 标注与出站脱敏仍是硬约束。
- **测试**：新增配置化护栏单测、默认值/审计单测、组件与 e2e 断言；回归全量。