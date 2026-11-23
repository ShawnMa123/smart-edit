# Design

## Context

See `proposal.md`、`specs/automation-workbench/spec.md`、`specs/editor-variables/spec.md`。

当前实现：

- `AutomationPanel` 只有 create fixture run → result → accept/apply/undo；没有 template、variable 或 downstream mapping。
- Template 区域只有名称输入 + `Save as template` + 纯文本 `<li>` 列表；capture 只生成 metadata，不保存正文；没有预览、详情、重命名或删除；模板只存在于组件 state，刷新即丢失。
- `RichDocument`/`projectDocument` 没有 variable node；`app/documents/projection.py` 对未知 inline 节点会丢字符。
- `document_drafts.variables_json` 只有 opaque map/version，没有 variable definition/occurrence。
- `app/templates/adidas-guarantee.yaml` 是 audit template pack，不是可复用的 document template。
- 后端没有 ExternalApiTemplate / mapping / payload。
- `web/src`、`app/`、`fixtures/` 里没有任何 OpenAPI/Swagger 解析；`package.json` 没有 YAML 依赖，也没有文件下载/Blob 工具（`Export` 仍是 not implemented）。
- `templateStore` 只有 capture/rename/remove，没有“更新同一条 template 的版本”操作；mock downstream templates 是硬编码 fixture，matching 是关键词匹配。
- 没有 downstream system 实体：没有 name/baseUrl/env/auth/spec 绑定；OpenAPI spec 只存在页面内存，刷新丢失；没有发送端点、代理或凭据存储。

本 change 做前端工作台；template 捕获内容保存在浏览器本地（非服务端）；OpenAPI JSON 在浏览器内解析并用于下载/mock send；唯一后端兼容修改是 variable node 的 canonical projection parity。

## Goals / Non-Goals

**Goals:**

- 把 Automation tab 从单一 fixture run 变成 Template / Variables & Fill / Downstream Mapping 三块工作台。
- 用真实 TipTap `variableReference` 节点验证“选中文本 → 标记变量 → 多 occurrence 预览”。
- 用 mock adapter/fixture 跑通 variable fill、downstream mapping/payload preview；template capture 走浏览器本地 store。
- Template 捕获前可预览来源/摘要，保存后可检查、重命名、删除，并在同一浏览器刷新后保留。
- 标记变量后可把当前文档保存到某个已有 template（同一记录 version+1，快照替换）。
- 上传/粘贴 OpenAPI 3.x JSON，选择 operation，把可用变量映射到 request schema 字段，预览并下载 JSON 文件。
- 在 Downstream Mapping 内管理下游系统（name/baseUrl/env/enabled/auth hint/绑定 spec），浏览器本地持久化并 mock 预置。
- 对 ready payload 执行不触网的 mock send（200/500），展示模拟 receipt，绝不调用真实下游 API。
- 除 template/下游系统浏览器本地存储、OpenAPI 本地解析外保持 fixture-only 边界；不接真实模型或外部系统。
- 让后续后端 P1/P2 只需替换 mock adapter/存储，不改页面结构。

**Non-Goals:**

- template 服务端持久化、跨设备同步、服务端版本库 API、template 版本历史/回滚。
- 用模板新建 document/draft（本 change 只应用到当前 editor 或更新已有 template）。
- YAML / Swagger 2.0 / 从 URL 拉取 spec / 外部 `$ref` / `oneOf`·`anyOf` 的完整 OpenAPI 支持。
- 下游系统/凭据的服务端 DB、真实 HTTP 发送/后端代理、真实 token 存储、发送历史/审计/重试/幂等。
- 真实 extract/confirm、完整 JSON Schema 验证、真实语义匹配/模型。
- 真实 API template 导入/审核/发布。
- compare/rewrite/voice。

## Decisions

### D1 三块工作台取代单一 fixture run

Automation tab 内部使用三个区域：

```
Template | Variables & Fill | Downstream Mapping
```

现有 `AutomationPanel` 的 fixture run/apply/undo 不再是主视图；保留为 `FixtureRunPanel`（debug/legacy）或删除出主 UI，具体由实现选择，但不得占据三块工作台的主流程。后端 run core 不变，仍由 API/测试覆盖。

替代：把 template/mapping 塞到 fixture run 面板下方。会让“Automation”仍然像一个 run 面板，不采用。

### D2 Template 是 document template 快照，存于浏览器本地

Template 区域在 capture 时一次性写入：

```
template_id, name, version, captured_at
source: imported(deterministic|heuristic|fallback, provenanceNote?) | edited-in-browser
bound_revision: number | null
char_count, variable summary (label/type/required/count)
rich_document (captured rich JSON)
```

存储位置是浏览器 `localStorage`（D13），不是组件内存，也不是服务端。UI 明确写 `Saved in this browser — not on the server`；Template 区域还保留 `Fixture-backed workbench` 总标注，但说明只有 template 是浏览器本地，variable fill 与 mapping 仍是 fixture。template 是快照：之后编辑 working document 不会改变已捕获的 content。不复用 `app/templates/adidas-guarantee.yaml`，那是 audit pack。

### D3 VariableReferenceNode 模型

```ts
interface VariableReferenceNode {
  type: 'variableReference';
  attrs: {
    variableId: string;
    label: string;
    valueType: 'string' | 'amount' | 'date' | 'currency';
    required: boolean;
    displayValue: string | null;
    occurrenceId?: string;
  };
}
```

TipTap：

- `group: 'inline'`, `inline: true`, `atom: true`；
- chip 显示 `displayValue ?? '{{label}}'`；
- 不可直接编辑；删除是结构操作；
- 右键/键盘动作 `Mark as variable` 只对单块非空选区可用；
- textarea fallback 只显示 `{{label}}`，禁用变量动作。

### D4 选区到变量

用户选中一段文本 → 打开 `Mark as variable` → 填写 label/type/required → 确认：

```
selected text -> one variableReference node
displayValue = selected text (initial)
variableId = mock id
occurrenceId = mock id
```

本 change 不把 variable 写入后端 variable table；variable list/occurrence 由 mock workbench state 管理。后续 P1 后端再把 variableId/occurrenceId 换成服务端生成。

### D5 Projection parity

前端 `projectDocument()` 与 `app/documents/projection.py` 对 variable node：

```
displayValue 存在 -> displayValue
displayValue 为空 -> {{label}}
```

这是唯一的后端代码兼容修改，防止 autosave 后正文投影丢失变量值。`replace_text` / 未来 `set_variable` 的跨变量校验属于后续后端 change。

### D6 Mock workbench adapter

新增 `web/src/automation/mockWorkbench.ts` + `fixtures/automation/workbench_demo.json`：

```ts
interface WorkbenchMock {
  suggestDefinition(selectedText): VariableDefinition;
  createVariable(selection, definition): VariableDefinition;
  fillVariable(variableId, value): OccurrencePreview[];
  listDownstreamTemplates(): ApiTemplateSummary[];
  mapDownstream(templateId, document): MappingCandidate[];
  confirmMapping(fieldId, value): MappingDecision;
  buildPayload(mapping, binding): PayloadPreview;
}
```

template 的 capture/list/rename/delete 不再放在 mockWorkbench，而由 D13 的 `templateStore`（浏览器本地）承载；`mockWorkbench` 只保留 variable/mapping/payload 的确定性 mock helper。所有方法同步/本地，不 fetch。UI 测试用同一个 mock + 注入的 `Storage`；后续后端 change 用 API adapter 替换。

### D7 Downstream Mapping mock

fixture 包含一个 synthetic API template：

```
template: application_type enum [guarantee, standby_dc]
document text: "... demand guarantee ..."
```

确定性匹配：

- 关键词/句式 -> candidate `guarantee`；
- 无候选/冲突 -> `missing`/`ambiguous`；
- 每个 candidate 带 evidence excerpt；
- 人工 confirm 后才进入 payload；
- payload preview 绑定 mock template version + document snapshot digest；
- 不发送。

### D8 错误与空态

- 无 draft：Template 仍可捕获本地内容，来源摘要显示 `no server draft`；Variables/Mapping 的依赖服务端 draft 的动作禁用并说明。
- 空文档：capture 禁用，说明模板需要文档内容。
- 空名称/空白 rename：拒绝并提示，不写 storage。
- 同名：提示会新增版本，不覆盖。
- 空列表：说明还没有 template，capture 会添加一个。
- storage 读取失败/不可用：显示可读消息，忽略无效条目；写入失败：条目标记 `Session only — browser storage failed`，不声称持久化。
- 无选区：`Mark as variable` 不可用，说明需要非空单块选区。
- fallback：变量动作禁用。
- 无下游模板/无字段/无候选/冲突：分别展示，不伪造 payload。

### D9 可访问性

- 三块区域用 `role="tablist"`/`tab` 或等价可键盘导航结构；
- 右键动作必须同时有工具栏/键盘入口；
- 变量 dialog 使用 label、焦点管理、Escape 关闭；
- 状态变化用 `aria-live`；
- 不能只用颜色表达 missing/ambiguous。

### D10 测试与迁移

- 新增 `VariableReferenceNode` 投影/选区测试（pageBreak/emoji/CJK 保持）。
- `AutomationWorkbench` 组件测试：三块区域、template capture、mark variable/fill、downstream mapping/payload、空态。
- `templateStore` 单测（注入 `memoryStorage`）：捕获/读取、刷新后恢复、sequence 不回退、20 个上限与淘汰、corrupt JSON/无效条目、`getItem`/`setItem` 抛错、rename/remove 持久化。
- Template 组件测试：来源预览（imported/edited/no draft）、字符/变量摘要、空文档禁用、空名称拒绝、同名提示、capture/list/detail、rename（空值拒绝）、delete 两步确认、storage 失败 session-only、unreadable 提示、切换 area 保留状态。
- `AssistantPanel` 仍断言 Automation tab；内容从 fixture run 改为 workbench。
- `draft.spec.ts`/`knowledge.spec.ts`/`errors.spec.ts` 更新：Automation 主视图是 workbench；fixture run 若保留则作为 debug 区域。
- `automation-workbench.spec.ts` 增加真实浏览器 flow：capture → reload → 列表仍在 → rename → 两步 delete，并断言 `Saved in this browser — not on the server`。
- `how_to_use.md`/`web/README.md` 更新三块工作台、template 浏览器本地边界与容量、失败降级文案。

### D11 归档顺序

`automation-tab` 已修改 `document-editor` tab 文案；本 change 进一步改变 Automation tab 内容。归档顺序：

```
agent-knowledge
  -> document-host-foundation / automation-run-core
  -> automation-tab
  -> automation-workbench-ui
```

若 `automation-tab` 未归档，先应用/归档它，避免 `document-editor` 与 `automation-workspace` delta 冲突。

### D12 Capture 预览与来源判定

Template 区域不使用第二个 modal；capture 卡片本身就是确认面：

```
┌ Capture current document ──────────────────────────┐
│ Name: [Demand guarantee template]      (v4)       │
│ Source: Imported · heuristic (font_size_1.42x)    │
│ Revision: 12 · 1,240 characters · 3 variables     │
│ Variables: amount(amount, required), beneficiary… │
│ ⚠ "Demand guarantee template" exists; saving adds v4│
│ Saved in this browser — not on the server         │
│ [ Save as template ]                              │
└───────────────────────────────────────────────────┘
```

- source：`document.provenance` 存在 → `Imported · <level>`，并显示 `provenanceNote`；不存在 → `Edited in this browser`。不推断文件名、上传人或“已验证来源”。
- revision：`draft?.revision ?? 'no server draft'`；没有服务端 draft 仍允许捕获本地内容。
- char count：`richToPlainText(document)` 的字符数（与 editor footer 一致）。
- variables：`collectVariables(document)` 的 label/type/required；只做展示，不写服务端 variable table。
- 空文档（无文本且无块）禁用捕获并说明原因；空白名称在提交时拒绝，不写 store。
- 同名模板已存在时提示“另存为新版本 vN”，绝不覆盖；取消则原模板不变。
- 主按钮 `Save as template` 是显式确认；没有隐式自动保存。

### D13 浏览器本地 template store

新增 `web/src/automation/templateStore.ts`：

```ts
interface TemplateRecord {
  id: string; name: string; version: string;
  source: { kind: 'imported'; provenance: Provenance; note?: string }
        | { kind: 'edited' };
  boundRevision: number | null;
  charCount: number;
  variables: Array<{ label: string; valueType: string; required: boolean }>;
  capturedAt: string;
  rich: RichDocument;   // captured snapshot, not a live reference
}

interface TemplateStore {
  list(): TemplateRecord[];
  capture(input: CaptureInput): { record: TemplateRecord; persisted: boolean };
  rename(id: string, name: string): TemplateRecord | null;
  remove(id: string): boolean;
  issue(): 'unreadable' | 'unavailable' | null;
}
```

- 复用 `versionStore.ts` 的模式：`memoryStorage()` / `defaultStorage()`、可注入 `Storage`（Node 测试无 `--localstorage-file`）。
- key：`smart-edit:automation-templates`（全浏览器共享，不按 document 分库）；payload `{ schemaVersion: 1, nextSequence: number, templates: TemplateRecord[] }`。
- `nextSequence` 持久化，保证刷新后版本号不回退；`version = 'v' + sequence`。
- 读取时逐条校验（id/name/version/source/rich 形状）；无效条目忽略并返回 `unreadable`，不渲染占位模板。
- `getItem/setItem` 抛错（隐私模式、配额）→ `unavailable`；`capture`/`rename`/`remove` 的写入失败必须返回 `persisted: false`，UI 保留 session-only 条目并标注。
- `MAX_TEMPLATES = 20`，newest first，超出淘汰最旧；UI 写明容量。
- 只存浏览器本地；不 fetch、不写服务端。schema 变化时清空旧 payload（旧模板只含 metadata，无法当模板内容使用）。

### D14 列表、详情与管理

- 列表为卡片按钮（`<ul>`/`<li><button aria-pressed>`），显示 name、version、source badge、capturedAt、charCount、variable 数；按 newest first。
- 选中卡片显示详情：完整 metadata + 投影前 240 字符摘录 + variable 列表 + `Captured content` 标签；详情只读 `record.rich`，不读当前编辑器。
- Rename：inline input（label “Template name”）+ `Save name` / `Cancel`；空白拒绝并提示；成功后 list/detail 更新，id/version/content 不变，写回 storage。
- Delete：第一次点击进入确认态（`Confirm delete` / `Cancel`），确认后才 `remove`；状态用 `aria-live` 宣布；取消保留。
- 空列表：说明“还没有 template；上方 capture 会添加一个”，不渲染假卡片。
- 切换 Variables/Mapping 再回来时，列表、选中项和确认态不得静默丢失（组件 state 保留）。

### D15 诚实边界与失败文案

- 固定文案：`Saved in this browser — not on the server`；容量：`Up to 20 templates · oldest removed first`。
- 写入失败：`Session only — browser storage failed`，条目仍可见但不可声称已持久化。
- 读取失败：`Stored templates could not be read; new captures will still work in this session`。
- 不调用 template 服务端 endpoint，不生成 server receipt，不把浏览器本地存储写成“已保存到服务器”。
- Template 区域的 `Fixture-backed workbench` 总 banner 保留，但明确只有 variable fill / mapping 是 fixture；template 是浏览器本地。

### D16 可访问性

- 卡片列表使用列表语义；卡片按钮的 accessible name 包含 name + version。
- Rename input、`Save name`、`Delete`、`Confirm delete` 都有可读 label；Escape 取消 rename/delete 确认；确认后焦点回到列表项。
- 状态变化（capture/rename/delete/storage 失败）用 `aria-live` 文本，不只用颜色。
- 键盘可完成 select → rename → confirm delete 全流程；Tab 顺序与视觉顺序一致。

### D17 Apply template 到当前 editor

```text
Template detail
  [Apply to editor]
       |
       +-- !richEditorAvailable ----------> disabled + "needs the rich editor"
       |
       +-- current text.trim() empty -----> apply directly
       |
       +-- current text has content ------> inline two-step confirm
                                             "Replace the current document?"
       |
       v
  onApplyTemplate(record)
       |
       v
  App: next = deep copy of record.rich
       replaceDocument(next, { confirm: false })
       setPane('editor') + setKnowledgeSelection(null) + scheduleSave(next)
       |
       v
  Workbench: register applied variables + notice
```

- **整篇替换，不做插入**：旧文档整体消失，因此模板里的 `variableId`/`occurrenceId` 不需要重映射。
- **保留捕获值**：apply 原样使用 `record.rich`（含 `displayValue`）；模板本身不变，apply 只读快照。
- **深拷贝**：App 拿到的文档不能与 `templateStore` 的记录共享引用；editor 后续编辑不得改动已存模板。
- **provenance 跟随内容**（D2/D12）：模板来自 imported 文档时，应用后的文档保留该 provenance/note；apply notice 写清模板名与版本，避免被误认为“重新导入”。
- **确认**：当前文档有内容才两步确认；空文档直接应用。确认使用 detail 内联确认（与 delete 一致），不用 `window.confirm`。
- **boundRevision 是捕获元数据**：detail 文案改为 `Captured at revision N`（或 `Captured without a server draft`），不暗示与当前 draft 绑定。
- **undo**：`setContent` 的 `replaceWith` 会进入 ProseMirror history；实现时用测试确认 Ctrl+Z 可回到应用前。不额外做 Undo UI，也不自动 capture 浏览器版本。
- **conflict**：允许 apply；应用内容按 local 处理，既有 conflict 面板仍是唯一解决路径，不声称冲突已解决。
- **fallback**：rich editor 不可用时 apply 禁用并说明原因。
- **变量登记**：从 `record.rich` 用 `collectVariables` 把 top-level 变量加入 `knownVariables`，使 applied required 变量被删除时仍能报告 missing；table 内变量仍受现有限制。

### D18 Save to template：更新同一条 template 的新版本

- 入口：Variables & Fill 的变量详情/列表提供 `Save to template`；打开一个已有 template 的下拉选择（不新增 modal）。没有 template 时禁用并提示先 capture。
- 两步确认：`Update "Name" (current vN → vN+1) with the current document? The previous snapshot will be replaced.` → `Update template` / `Cancel`。取消不改任何东西。
- `templateStore.update(id, input)`：
  - 保留 `id`/`name`，`version = 'v' + nextSequence`，`capturedAt = now`；
  - 用当前文档替换 `rich`、`source`、`boundRevision`、`charCount`、`variables`；
  - 与 capture 一样写浏览器存储；写失败返回 `persisted: false`，列表保留 session-only 的新快照，reload 可能恢复旧快照（诚实）。
- 版本号继续使用全局 `nextSequence`（不是每模板连续）；文档里明确这是 build 的简化。
- 没有版本历史/回滚：更新后旧快照不可恢复；列表卡片原地更新，detail 立刻显示新版本与 capturedAt。
- 更新只改 template，不改当前 editor；之后 `Apply to editor` 使用新快照。

### D19 OpenAPI JSON → 下游请求 JSON

Source 与解析：

```text
Downstream Mapping
  Source: (Synthetic fixture) | (OpenAPI JSON)
  OpenAPI JSON:
    [Choose .json]  [Paste JSON textarea]  [Parse]
        |
        v
  OpenAPI 3.x JSON only (no YAML / Swagger 2.0 / URL / external $ref)
    - operations: paths × methods with requestBody.content['application/json'].schema
    - resolve local $ref (#/components/schemas/...), detect cycles
    - flatten object properties into dotted paths; keep type/required/enum
    - unsupported oneOf/anyOf/external refs are listed, not guessed
```

- 上传/粘贴的 spec 只存在页面内存；刷新丢失，不写 localStorage，不发网络请求。
- operation 列表显示 `METHOD /path` 与 `operationId`；没有 JSON requestBody 的 operation 显示为不可用。
- 变量映射：按规范化后的 variable label 与字段名（最后一段）自动建议；每个字段可用 select 手动改；同一变量可复用；required 缺失、enum 不匹配、number/integer/boolean 转换失败都让 preview `not_ready`，并指出字段。
- 类型转换只做明确的字符串→数字/布尔；失败不静默；不对 object/array 做自动推断（只接受已映射的标量，嵌套对象按点号路径组装）。
- 生成：按 dotted path 组装嵌套对象；未映射的 optional 字段省略；required 全部满足才 `ready`。
- 预览与下载：`web/src/automation/payloadExport.ts` 用 Blob + object URL + `<a download>` 生成 `.json`；文件名 `${operationId || 'request'}-<timestamp>.json`（sanitize）；下载后 revoke URL。UI 固定显示 `Not sent`，没有 send/execute 按钮，不调用下游 API。
- 现有 synthetic fixture 模式保留为 demo；OpenAPI 模式共用 mapping 表/preview 的视觉，但使用真实解析出的字段。两者不混用。

### D20 下游系统注册表（浏览器本地）

```ts
interface DownstreamSystem {
  id: string;
  name: string;
  baseUrl: string;              // http(s)
  environment: 'sandbox' | 'production';
  enabled: boolean;
  auth: { type: 'none' | 'api_key' | 'bearer'; hint?: string };  // no real secret
  specText: string;             // OpenAPI 3.x JSON bound to this system
  specUpdatedAt: string;
  createdAt: string;
  updatedAt: string;
}
```

- 新文件 `web/src/automation/downstreamSystemStore.ts`，模式与 `templateStore.ts` 一致：可注入 `Storage`、key `smart-edit:automation-downstream-systems`、`schemaVersion: 1`、payload `{schemaVersion, systems}`。
- 首次读取且 key 不存在时，从 `fixtures/automation/downstream_systems.json` 种入 mock 预设（sandbox 系统绑定 `openapi_sample.json`，一个 disabled production 系统）；之后以 localStorage 为准；全删后不重新种入。
- 上限：`MAX_SYSTEMS = 10`；`MAX_SPEC_BYTES = 512 * 1024`（按 UTF-8 字节）；超限拒绝并提示。损坏/无效系统逐条忽略；写失败报告 `Session only — browser storage failed`，reload 可能回到旧值。
- CRUD：`list/get/create/update/remove`。name/baseUrl 必填，baseUrl 必须 `http(s)`；删除需两步确认。auth 只接受 type/hint，不接收真实 token；UI 以 `mock · <hint>` 展示。
- UI 在 Downstream Mapping 内：system selector + 可折叠 `Manage systems`（列表 + 表单：name/baseUrl/env/enabled/auth type/hint/spec 文件或粘贴）。不新增第四个 area。
- 选择系统 → 解析 `specText` → 重置 operation/mapping；切换/删除系统清空对应状态；document variables 保留。spec 的编辑只在 `Manage systems` 保存；mapping 区不使用未保存的临时 spec（因此 OpenAPI mode 必须先选系统）。
- 未来 DB：只替换 store 实现（`list/get/create/update/remove`），UI 与 spec 绑定规则不变；真实 token 由服务端保管，浏览器只保存 hint。

### D21 Mock send

`web/src/automation/mockDownstreamSend.ts`：

```ts
interface MockSendInput {
  system: DownstreamSystem;
  operation: { method: string; path: string; operationId?: string };
  payload: Record<string, unknown>;
  simulateFailure: boolean;
  now?: Date;
}

interface MockReceipt {
  simulated: true;
  status: 200 | 500;
  requestId: string;
  method: string;
  endpoint: string;          // baseUrl + path
  sentAt: string;
  payload: Record<string, unknown>;
  outcome: 'mock_success' | 'MOCK_DOWNSTREAM_ERROR';
  message: string;
}
```

- 纯函数、无 `fetch`/代理/凭据读取：成功返回 200 `mock_success`；`simulateFailure` 返回 500 `MOCK_DOWNSTREAM_ERROR`。
- requestId：`mock_<operationId|method>_<epoch>`，`now` 可注入以便测试。
- UI gating：system enabled + operation selected + payload ready；`Send (mock)` 按钮 + `Simulate failure` checkbox（默认关）；未满足时禁用并说明缺少什么。
- Receipt：endpoint、status、requestId、时间、payload、`Simulated — no network request`；只显示最近一次，不持久化、不写历史/审计。
- `Download JSON` 保持独立且不受 mock send 影响。
- 未来真实发送：后端 endpoint + allowlist/timeout + 服务端凭据 + audit；不在本 change。

### D22 Beneficiary matcher label variants

`synthetic Downstream Mapping` 的 beneficiary matcher 当前只接受 `Beneficiary:`，因此 `Beneficiary name: aabbcc` 会落入 missing。修正为：

```text
/beneficiary(?:\s+name)?\s*[：:]\s*([^\n.]+)/i
```

- 接受 `Beneficiary:` / `Beneficiary :` / `Beneficiary name:` / `Beneficiary Name :`（大小写、空白、全角/半角冒号）。
- evidence 使用同一规则（`sentenceWith`），确保候选与依据一致。
- 仍必须有冒号和非空值；普通提及 “Beneficiary name is ...” 不匹配。
- `realValue()` 继续拒绝 `{{...}}` 占位符，占位符仍是 `missing`。
- 单元测试覆盖：`Beneficiary name: aabbcc`、`Beneficiary: aabbcc`、大小写/空白、占位符 missing、无冒号 missing；组件测试覆盖 v2 template 的 `beneficiary_name` 变成 `matched`，确认后进入 payload。

### D23 Expiry date normalisation

`synthetic Downstream Mapping` 接受多种日期写法，但**统一输出 ISO `YYYY-MM-DD`** 后才进入 payload：

- 支持：`2027-03-12` / `2027/03/12` / `2027.03.12`、`12/03/2027`、`12/03/27`、`2027年3月12日`、`12 March 2027`、`March 12, 2027`（月份名大小写不敏感）。
- 两位年份：`00–69` → `2000–2069`；`70–99` → `1970–1999`（合同日期通常在未来，27 → 2027）。
- 分隔日期默认 **DD/MM**：`12/03/27` → `2027-03-12`。只有当第二段 >12 且第一段 ≤12 时按 MM/DD 解释（如 `12/31/2027`），避免把无歧义的美式日期误读。
- 只接受真实日历日期（闰年/月份天数）；`31/02/2027` 保持 `missing`。
- 选择文档中最早出现且可解析的日期 token；evidence 使用包含该 token 的整行。
- 该 policy 是 mock matcher 的确定性规则，不做 locale 推断；真实后端可替换为更完整的解析/确认流程。

## Risks / Trade-offs

- [mock 被误认为真实 template/映射] → UI banner、fixture limitation、文档、测试同时声明。
- [浏览器本地 template 被误认为服务端持久化] → 固定文案 `Saved in this browser — not on the server`；文档/测试同时断言；不提供任何 server receipt。
- [localStorage 配额、损坏或隐私模式] → schema 校验、逐条忽略无效项、`unreadable`/`unavailable` 提示、写入失败降级为 session-only 并明示。
- [template 内容过大] → 最多 20 个、newest first、最旧淘汰；写失败不静默截断，按 session-only 处理。
- [apply 整篇替换造成内容丢失] → 有内容时两步确认；空文档直接应用；undo 依赖 editor history 并在实现时验证；不自动 capture 版本（与现有 import 行为一致）。
- [applied provenance 造成来源误读] → provenance 跟随内容；apply notice 明确模板名/版本，capture preview 仍只描述已存 provenance。
- [applied variables 未进入 missing 追踪] → apply 时把 top-level 变量登记到 `knownVariables`；table 内变量沿用现有限制。
- [OpenAPI 子集被误认为完整支持] → UI/文档/错误文案明确仅 OpenAPI 3.x JSON + 本地 `$ref`；YAML/2.0/URL/外部 ref/oneOf/anyOf 明确报不支持。
- [类型转换伪造值] → 只做显式 number/integer/boolean 转换；失败/越界/枚举不匹配直接 `not_ready`，不静默写值。
- [下载文件被误认为已发送] → 固定 `Not sent`；下载只来自 preview，不触网。
- [mock send 被误认为真实发送] → receipt 固定 `Simulated — no network request`，无 fetch/proxy，不读 token，不写历史；文档/测试同时声明。
- [下游系统配置被误认为服务端 DB] → 固定 `Saved in this browser — not on the server`；未来 DB 只替换 store 实现。
- [localStorage 存真实凭据] → auth 只保存 type/hint，不提供 token 输入；真实发送时由服务端保管。
- [系统 spec 过大或写失败] → 系统上限 10、单 spec ≤ 512 KB；写失败报告 session-only 并保留旧值。
- [删除/切换系统导致状态错位] → 切换清空 operation/mapping 但保留 variables；删除选中系统清空 operation/mapping/receipt。
- [template 更新覆盖旧快照] → 两步确认并明示“previous snapshot will be replaced”；本 build 不提供历史/回滚。
- [未保存 spec 被用于 mapping] → OpenAPI mode 只使用选中系统已保存的 spec；spec 编辑仅在 Manage systems 保存。
- [日期 DD/MM 与 MM/DD 误读] → 默认 DD/MM；MM/DD 仅在第二段 >12 时使用；所有输出统一 `YYYY-MM-DD`；无效/歧义日期保持 missing；文档与测试同时声明。
- [variable node 与 projection/selection 偏移不一致] → 单一 projection + 测试；本 change 只做 parity，不做服务端 apply 校验。
- [工作台范围过大] → 三块 UI 都以 mock 为主；每块独立组件与测试，后端后续替换 adapter。
- [fixture run 入口被移除导致 e2e 失效] → 保留 debug 入口或更新 e2e 到新工作台；不隐藏已有 run core。
- [用户把 payload preview 当成已发送] → preview 固定 `Not sent`；只有显式 `Send (mock)` 产生 simulated receipt，且不触网。

## Migration Plan

1. 引入 variable node + projection parity + 测试。
2. 构建 workbench shell 与 mock adapter。
3. 实现 capture 预览、卡片列表/详情、rename/delete 与 `templateStore`（localStorage + 单元测试）。
4. 实现 apply：详情内两步确认、App 外部替换接线、变量登记与 undo 测试。
5. 实现 `Save to template`：`templateStore.update`（同 id/name，version+1，快照替换）+ Variables 详情入口与两步确认。
6. 实现 OpenAPI：`openapi.ts` 解析（3.x JSON/本地 `$ref`/flatten/required/enum）、Downstream Mapping OpenAPI 模式、变量映射与类型校验。
7. 实现 `payloadExport.ts` 下载与 preview 接线。
8. 实现 downstream system：`downstreamSystemStore` + `fixtures/automation/downstream_systems.json` + `Manage systems` CRUD + system↔spec 绑定。
9. 实现 mock send：`mockDownstreamSend.ts`（200/500）、`Send (mock)`、`Simulate failure` 与模拟 receipt。
10. 替换 Automation tab 主视图；fixture run 移到 debug/legacy（或保留但非主流程）。
11. 更新测试/e2e/docs（含刷新后模板/系统仍在、apply 后可编辑、template 更新、OpenAPI 下载、mock send 成功/失败）。
12. 回滚：移除 `templateStore`/`downstreamSystemStore` 与对应 localStorage key（或忽略 store、回到 session-only）；移除 apply/update 接线、OpenAPI 模式与 mock send；恢复 `AutomationPanel` fixture run、移除 variable node；后端 projection parity 可保留（对普通文档无影响）。

## Open Questions

- Template 的“字段/Schema 摘要”在 P1 之前是否只从 variables 推导？本 change 可以先显示 variable/field 数。
- “Mark as variable” 初始是否把选中文本作为 displayValue？本设计采用“是”，用户可以清空后再 fill。
- 下游模板导入是文件选择还是预置列表？本 change 用 mock 预置列表 + synthetic JSON，真实导入留 P2。
- 用模板新建 document/draft 何时做？本 change 只应用到当前 editor 或更新已有 template，不创建新 draft；新建/跨文档留后续。
- OpenAPI 只支持 3.x JSON + 本地 $ref；Swagger 2.0/YAML/URL/外部 ref/oneOf/anyOf 是否在后续 change 支持？
- Template 版本号沿用全局 sequence（不是每模板连续）；是否需要在后续引入 per-template 版本历史/回滚？
- 下载文件名用 `${operationId || 'request'}-<timestamp>.json`；是否需要让用户自定义文件名？
- 下游系统 auth：本 build 只存 type/hint；真实 token 由服务端保管，何时接入？
- 下游系统上限 10、单 spec ≤ 512 KB 是否合适？种子系统全删后是否需要“恢复预设”？
- mock send 是否需要保存最近 N 次 receipt/审计？本 change 只显示最近一次。
- 真实发送何时做：后端 endpoint + allowlist/timeout/凭据/审计/幂等，需要单独 change。
- 单模板大小是否还需要按字符数二次限制？本 change 先用 20 个上限 + 写失败降级，真实容量策略留服务端阶段。