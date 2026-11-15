# Proposal

## Why

当前 Automation tab 只有 `rewrite/replace_text` 的 fixture run，和产品上的 Automation 助手不匹配：用户不能把当前文档存为 template、不能在正文里选中文本并标记为 variable、也不能导入下游 API template 并生成 JSON payload 预览。先完成前端工作台，用同一套 DTO + mock 数据把三块交互跑通，再按后端阶段替换数据源，避免 UI 结构反复返工。

第一轮 Template 区域已经能用，但界面不合格：只有一个名称输入框、一个 `Save as template` 按钮和一串纯文本列表；用户在保存前看不到“将被保存的是什么”（文档是导入还是本地编辑、多少字符、哪些 variable、哪个 revision），保存后不能查看、重命名或删除，刷新页面模板全部消失。本 change 继续在同一 change 内优化 Template 区域：捕获前预览 + 确认、卡片式列表与详情、重命名/删除，并用浏览器本地存储跨刷新保留（仍明确不是服务端持久化）。

## What Changes

- **Automation 工作台三块区域**：
  - `Template`：把当前导入/编辑的文档存为 template。捕获前显示 live preview（来源 imported/edited、draft revision、字符数、variable 摘要、名称与下一个版本；同名时提示会新增版本），用户显式确认后保存 rich document + metadata；卡片式列表支持选中查看详情（内容摘录、来源、variable、捕获时间）、重命名、两步确认删除；空态给出下一步说明。
  - `Template` 应用：在详情区提供 `Apply to editor`，用模板快照**替换当前整篇文档**并在 editor 继续编辑。当前文档有内容时两步确认，空文档直接应用；模板里的 variable 保留捕获值；provenance 跟随内容；应用后走现有 autosave。模板本身保持不变。
  - `Template` 更新：标记变量后，Variables 详情提供 `Save to template`；选择一个已有 template，用当前文档生成**新版本快照**（同一 id/name，version+1），两步确认旧快照被覆盖；继续沿用浏览器本地存储与失败降级。
  - `Downstream Mapping` + OpenAPI：OpenAPI JSON 在浏览器内解析（本地 `$ref`、required、enum、基础类型、dotted path），选择带 JSON requestBody 的 operation，把可用变量映射到字段，预览并**下载 `.json` 文件**；真实发送不在本 change。
  - `Downstream system registry`：在 Downstream Mapping 内提供系统选择器与可折叠 `Manage systems`。系统包含 name、baseUrl、environment、enabled、auth type+hint、绑定的 OpenAPI spec；支持新增/编辑/删除，存浏览器 `localStorage`（首次从 mock 预设种入，最多 10 个系统、单个 spec ≤ 512 KB）。auth 只存类型/提示，不存真实 token。
  - `Mock send`：payload ready 且 system enabled 时可 `Send (mock)`；默认返回 200 `mock_success`，勾选 `Simulate failure` 返回 500 `MOCK_DOWNSTREAM_ERROR`。receipt 显示 method + endpoint、status、requestId、payload 与 `Simulated — no network request`；不触网、不读 token、不保存历史。
  - `OpenAPI` 与系统绑定：OpenAPI mode 必须先选中一个下游系统；系统自动加载其绑定 spec，spec 的编辑只发生在 `Manage systems`（上传/粘贴 + Save），避免出现“未保存 spec 却能发送”的歧义。切换系统会重置 operation/mapping，但保留共享变量。
  - `Template` 存储：使用浏览器 `localStorage`（可注入 `Storage`、schema version、最多 20 个、最旧淘汰）跨刷新保留；明确标注 `Saved in this browser — not on the server`，损坏/不可用/配额失败时诚实降级，不伪造已保存。
  - `Variables & Fill`：选中正文文本后右键 `Mark as variable`；创建 variable 定义（label/type/required）；显示所有 occurrence 与 before/after fill 预览。
  - `Downstream Mapping`：导入/选择一个 mock API template；显示目标字段、语义匹配候选（如 `application_type = guarantee`）、原文依据、逐字段确认，以及 JSON payload 预览；不发送外部请求。
- **真实 TipTap `variableReference` 节点**：inline atom、chip 显示、不可直接编辑、右键标记、删除受控；textarea fallback 只显示 `{{label}}` 并禁用变量操作。
- **投影 parity（唯一后端兼容修改）**：`app/documents/projection.py` 与前端 `projectDocument()` 对 variable node 使用同一规则（有值显示值，无值显示 `{{label}}`）；不新增 endpoint、schema 或运行合同。
- **mock-first**：除 Template 与下游系统的浏览器本地存储外，其余 UI 在 `Fixture-backed` 标注下运行；mock send 明确是模拟，不调用真实解析/模型/下游系统。
- **测试/文档**：更新 AutomationPanel/AssistantPanel 测试、新增 variable/template/downstream system/mock send 测试、更新 `how_to_use.md` / `web/README.md`。
- **明确不做**：template 服务端持久化/跨设备同步/版本库 API、用模板新建 document/draft、Swagger 2.0 / YAML / URL 拉取 / 外部 `$ref`、**真实 HTTP 发送/后端代理/DB CRUD/真实凭据存储/发送历史与审计/重试与幂等**、真实 extract/confirm、真实 API template 导入、真实语义匹配/模型、compare、rewrite、voice。它们由后续阶段实现。

## Capabilities

### New Capabilities

- `automation-workbench`: Automation tab 的三块前端工作台、mock 数据、fixture-only 标注、template/variable/downstream mapping 的 UI 状态与错误空态；Downstream Mapping 内的下游系统选择/管理入口与 mock send receipt；template 与下游系统配置可保存在浏览器本地（非服务端）；不覆盖后端生成/服务端持久化/真实发送能力。
- `downstream-api-contract`: 从系统绑定的 OpenAPI JSON 解析 operation 与 JSON request schema，把可用变量映射为字段；下游系统注册表（CRUD + 浏览器本地持久化 + mock 预设）；预览/下载 JSON 与不触网的 mock send（200/500）；不联网、不调用下游 API、不支持 YAML/Swagger 2.0/外部引用、不存真实凭据。
- `editor-variables`: 正文中的 variableReference 节点、右键标记为变量、occurrence 展示、textarea fallback，以及前后端 canonical projection 对变量节点的一致规则。

### Modified Capabilities

<!-- 无 durable capability 被修改；automation-tab 的 automation-workspace 仍未归档，本 change 用新的 automation-workbench 承载工作台行为。归档时按顺序合并。 -->

## Impact

- **前端**：`AutomationWorkbench.tsx`（下游系统选择器 + 可折叠 Manage systems + mock send receipt；OpenAPI 只读系统绑定 spec）、新增 `web/src/automation/downstreamSystemStore.ts`（localStorage CRUD + mock 预设 seed）、`mockDownstreamSend.ts`（不触网 200/500）、`fixtures/automation/downstream_systems.json`、`templateStore.ts`、`templateCapture.ts`、`openapi.ts`、`payloadExport.ts`、`mockWorkbench.ts`、`styles.css`、Vitest/Playwright、`how_to_use.md`、`web/README.md`。
- **后端**：仅 `app/documents/projection.py` 变量节点投影兼容；不改 API、SQLite schema、run/apply/undo，也不新增 template 或发送 endpoint。
- **数据/依赖**：0 个新依赖；fixture 放在 `fixtures/automation/`；template 与下游系统配置存于浏览器 `localStorage`（系统 key `smart-edit:automation-downstream-systems`）；下游系统 spec 绑定该系统；不存真实 token。
- **风险**：浏览器本地持久化被误认为服务端保存；必须标注 `Saved in this browser — not on the server`。下游系统 spec 可能较大或写入失败，需要上限与诚实降级。Mock send 可能被误认为真实发送；必须固定 `Simulated — no network request`、不调用 fetch/proxy、不读 token。Template 更新/Apply 的覆盖语义仍需确认。OpenAPI 子集（3.x JSON、本地 $ref、不支持 YAML/2.0/oneOf/anyOf/外部引用）必须明示。