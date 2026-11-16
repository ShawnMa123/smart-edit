# Tasks

> 依据：`proposal.md`、`specs/automation-workbench/spec.md`、`specs/downstream-api-contract/spec.md`、`specs/editor-variables/spec.md`、`design.md`（D1–D23）。
> 边界：前端工作台 + mock；template 与下游系统配置保存在浏览器本地（非服务端），template 可 apply/更新；OpenAPI JSON 在浏览器内解析，支持下载与不触网的 mock send；variable/mapping 的 synthetic 模式仍为 mock；不改后端 API/schema/run/apply 合同。唯一后端兼容修改是 variable node 的 projection parity。

## 1. VariableReferenceNode 与投影

- [x] 1.1 `web/src/rich/richDocument.ts` 增加 `VariableReferenceNode`（inline atom，attrs: variableId/label/valueType/required/displayValue/occurrenceId），并更新 `isRichDocument` 的 block/inline 校验。Verify: 类型测试/现有 richDocument 测试通过。
- [x] 1.2 `web/src/rich/tiptap.ts` 注册 `variableReference` node：inline atom、chip 渲染、不可直接编辑、删除受控。Verify: `RichEditor` 能渲染 chip；普通文本编辑不破坏节点。
- [x] 1.3 `web/src/rich/projection.ts` 与 `app/documents/projection.py` 对 variable node 使用同一规则：有值显示值，无值显示 `{{label}}`。Verify: 前后端 golden fixture 一致；pageBreak/emoji/CJK 不变。
- [x] 1.4 `web/src/rich/selection.ts`：选区到变量转换只接受单块非空 paragraph/heading；跨块/表格/空选区返回不可用。Verify: 单测覆盖合法/跨块/emoji/CJK。
- [x] 1.5 textarea fallback：显示 `{{label}}`；禁用 mark-as-variable/fill，并说明需要 rich editor。Verify: `RichEditor` fallback 测试更新。

## 2. Workbench shell 与 Template

- [x] 2.1 新增 `AutomationWorkbench` 容器：三个区域 `Template` / `Variables & Fill` / `Downstream Mapping`；fixture-only banner 与未实现列表。Verify: 组件测试断言三个 tab、banner、Legal/未实现边界。
- [x] 2.2 Template 区域（初版）：capture 当前 draft 为 session-only mock template（name/version/revision/variable 摘要）；template 列表；明确 `Fixture-backed` 边界。Verify: 组件测试覆盖 capture/list/空态。**已被 7.x 的 capture 预览、管理与浏览器本地持久化取代，保留为历史记录。**
- [x] 2.3 mock state：`web/src/automation/mockWorkbench.ts` + `fixtures/automation/workbench_demo.json`，提供 template/variable/downstream 数据；不 fetch。Verify: mock 单测/同一 fixture 被 UI 测试复用。
- [x] 2.4 `AutomationPanel` 主视图切换为 workbench；fixture run 保留为 `FixtureRunPanel` debug 区域或移除出主流程。Verify: AssistantPanel 测试看到 workbench，不再以 fixture run 为主视图。

## 3. Variables & Fill

- [x] 3.1 选区右键菜单 + 工具栏/键盘入口 `Mark as variable`；dialog 收集 label/type/required。Verify: 组件测试覆盖右键、键盘、空选区、fallback。
- [x] 3.2 确认后把选区替换为一个 variableReference（初始 displayValue=选中文本），并在 mock variable list 中登记。Verify: 单测断言节点、variableId、occurrence、undo。
- [x] 3.3 Variables 列表：value/type/required/occurrence 列表；选择变量显示所有 occurrence。Verify: 组件测试覆盖多 occurrence、不同文本、缺失 required。
- [x] 3.4 Fill 预览：输入新值后显示每个 occurrence 的 before/after；确认更新所有 occurrence，不改同名普通文本。Verify: 组件测试覆盖 before/after、同名普通文本不变。
- [x] 3.5 错误/空态：无 draft/无变量/无 occurrence/fallback；不伪造已保存或服务端 receipt。Verify: 组件测试。

## 4. Downstream Mapping

- [x] 4.1 Downstream Mapping 区域：mock API template 选择器、目标字段列表、覆盖/缺口状态。Verify: 组件测试覆盖选择模板/空字段/缺失模板。
- [x] 4.2 确定性 mock 匹配：`application_type` enum `[guarantee, standby_dc]`；文档含 guarantee -> candidate `guarantee` + evidence excerpt；无候选/冲突 -> missing/ambiguous。Verify: mock 单测与组件测试。
- [x] 4.3 逐字段确认/纠正：未确认不进入 payload；显示 `Not sent`，无 send 按钮。Verify: 组件测试断言 payload 不含未确认字段、无外部调用。
- [x] 4.4 Payload preview：JSON tree/text、模板版本与文档 digest 绑定；缺口时 `mapping_not_ready` 状态。Verify: 组件测试覆盖 ready/not-ready。

## 5. 可访问性、测试与文档

- [x] 5.1 三块区域 tab 键盘可达；Mark as variable 有键盘入口；dialog focus/Escape；状态 `aria-live`。Verify: 组件测试 + 手工键盘检查。
- [x] 5.2 更新 `AssistantPanel.test.tsx`、`AutomationPanel.test.tsx`、`RichEditor`/projection/selection 测试。Verify: 相关 Vitest 全绿。
- [x] 5.3 更新 `how_to_use.md` / `web/README.md`：三块工作台、fixture 边界、template 浏览器本地（非服务端）、payload 不发送、未实现列表。Verify: 文档与组件文案一致。
- [x] 5.4 Playwright：更新/新增 `web/e2e/automation-workbench.spec.ts`，覆盖三块区域、mark variable/fill、mapping/payload。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/automation-workbench.spec.ts --project=desktop`。

## 6. 集成验收

- [x] 6.1 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`typecheck`、`build`。Verify: 全绿并记录测试数量。
- [x] 6.2 现有 e2e：`draft.spec.ts`、`knowledge.spec.ts`、`errors.spec.ts`、`layout.spec.ts`。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- --project=desktop`。
- [x] 6.3 手工场景：无 draft、无选区、fallback、同名普通文本、多个 occurrence、mapping 缺失/冲突、payload not-ready。Verify: 逐条对照 specs 记录；未通过项不得勾选。

## 7. Template 区域优化（预览 / 管理 / 浏览器本地持久化）

- [x] 7.1 新增 `web/src/automation/templateStore.ts`：`TemplateRecord`（快照 `rich`、`charCount`、`variables`、`source`、`boundRevision`）、可注入 `Storage`、`schemaVersion`/`nextSequence`、`MAX_TEMPLATES = 20`、`list/capture/rename/remove/issue`。Verify: 单测覆盖持久化、刷新恢复、sequence 不回退、淘汰最旧、corrupt/无效条目、`getItem`/`setItem` 抛错。
- [x] 7.2 捕获来源与摘要 helper：`document.provenance` → `Imported · deterministic/heuristic/fallback`（含 note），否则 `Edited in this browser`；draft revision 或 `no server draft`；字符数；`collectVariables` 摘要；下一个版本号；同名检测。Verify: 单测覆盖 imported/edited/no draft/同名/空文档。
- [x] 7.3 Capture 卡片：名称输入 + live preview（来源、revision、字符数、variable、下一个版本）+ 同名“另存为新版本”提示 + `Saved in this browser — not on the server`；`Save as template` 为显式确认；空文档禁用并说明；空白名称拒绝。Verify: 组件测试。
- [x] 7.4 卡片式列表 + 详情 + 空态：name/version/source/capturedAt/chars/variables；选中显示 240 字内容摘录 + variables + `Captured content`；详情只读快照；空列表说明 capture 会添加一个。Verify: 组件测试；捕获后编辑正文，模板内容不变。
- [x] 7.5 模板管理：inline rename（空值拒绝，id/version/content 不变）、两步确认 delete（取消保留）、操作写回 storage、状态 `aria-live`。Verify: 组件测试 + 键盘流程。
- [x] 7.6 刷新持久化与失败路径：同一 storage 重新挂载恢复列表；容量文案；storage unavailable/corrupt → 可读提示且不渲染假模板；写入失败 → session-only 标记与提示。Verify: 组件测试 + 单测。
- [x] 7.7 可访问性：卡片 accessible name（name + version）、rename/delete 的 label 与 focus/Escape、删除确认公告、Tab 顺序。Verify: 组件测试 + 手工键盘检查。
- [x] 7.8 文档与 e2e：更新 `how_to_use.md` / `web/README.md`（浏览器本地边界、容量、失败降级）；扩展 `web/e2e/automation-workbench.spec.ts` 覆盖 capture → reload → 列表仍在 → rename → 两步 delete。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/automation-workbench.spec.ts --project=desktop`。
- [x] 7.9 手工场景：imported 文档、纯本地编辑、无 draft、空文档、同名捕获、空名称/空 rename、storage corrupt、写失败、删除取消。Verify: 逐条对照 `specs/automation-workbench/spec.md` 记录；未通过项不得勾选。
- [x] 7.10 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`typecheck`、`build`、desktop e2e。Verify: 全绿并记录测试数量。

## 8. Apply template 到当前 editor

- [x] 8.1 新增 `web/src/automation/templateApply.ts`：`applyTemplate(record)` 返回深拷贝的 `rich` 与 top-level variable 登记信息；保证不改动记录、保留 `displayValue` 与 provenance。Verify: 单测覆盖保留值/provenance、深拷贝隔离、重复 apply 结果一致、记录不变。
- [x] 8.2 Template 详情增加 `Apply to editor`：当前文档有内容时两步确认（`Replace document` / `Cancel`），空文档直接应用；fallback 禁用并说明；应用后 notice、把 applied variables 登记到 `knownVariables`。Verify: 组件测试覆盖确认/取消/空文档/fallback/变量缺失报告。
- [x] 8.3 App 接线：新增 `onApplyTemplate` 绑定；App 用深拷贝文档走既有 `replaceDocument`（跳过 `window.confirm`）、`setPane('editor')`、清 selection、`scheduleSave`；conflict 状态下按 local 处理且不声称已解决。Verify: App/组件测试断言 editor 内容替换、dirty/autosave、conflict 文案。
- [x] 8.4 Undo 验证：确认外部 `setContent` 整篇替换后，editor history 的 undo 能回到应用前；若不能，暂停并更新 design/spec（不静默放弃）。Verify: `RichEditor`/`useRichEditor` 或 App 级测试。
- [x] 8.5 e2e：扩展 `web/e2e/automation-workbench.spec.ts`：capture 模板 → 修改当前文档 → apply → 确认 → editor 显示模板内容 → autosave 后 reload 仍为模板内容；覆盖取消不改变文档。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/automation-workbench.spec.ts --project=desktop`。
- [x] 8.6 文档与全量回归：更新 `how_to_use.md` / `web/README.md`（apply 行为、确认、保留值、provenance、`Captured at revision` 文案）；跑 pytest/vitest/typecheck/build/desktop e2e 并记录数量。Verify: 全绿。

## 9. Save to template（更新已有 template）

- [x] 9.1 `templateStore.update(id, input)`：保留 id/name，version 取下一个全局 sequence，替换 rich/source/boundRevision/charCount/variables/capturedAt；持久化；写失败返回 `persisted:false` 并保留 session-only 快照。Verify: 单测覆盖原地更新、version+1、其他 template 不变、reload 读新快照、写失败降级。
- [x] 9.2 Variables 详情增加 `Save to template`：选择已有 template → 两步确认（旧快照会被替换）→ 更新列表/详情并 `aria-live` 公告；无 template 时禁用并提示先 capture；空文档禁用。Verify: 组件测试覆盖确认/取消/无模板/写失败/updated snapshot 用于后续 apply。
- [x] 9.3 文档化 `Save to template` 的覆盖语义（无历史/回滚，version 为全局 sequence）。Verify: 文案与 `design.md` D18 一致。

## 10. OpenAPI JSON → 下游请求 JSON

- [x] 10.1 新增 `web/src/automation/openapi.ts`：OpenAPI 3.x JSON 解析、本地 `$ref`（含循环检测）、operation 列表（method/path/operationId）、`application/json` request schema、object properties flatten 为 dotted paths、required/enum/type；YAML/2.0/外部 ref/oneOf/anyOf 明确报不支持。Verify: fixture 单测覆盖 refs/cycle/required/enum/nested/unsupported/坏 JSON。
- [x] 10.2 Downstream Mapping 增加 source 选择 `Synthetic fixture | OpenAPI JSON`；OpenAPI 模式支持 `.json` 文件选择与粘贴 + Parse、标题/版本、错误与“仅本地解析/刷新丢失”文案；operation 选择器显示不可用 operation。Verify: 组件测试覆盖上传/粘贴/坏 spec/operation 选择/空态。
- [x] 10.3 变量→字段映射：label 规范化自动建议、select 手动覆盖、同一变量可复用；required 缺失、enum 不匹配、number/integer/boolean 转换失败 → `not_ready` 并指出字段；不静默转换。Verify: 组件测试 + 纯函数单测。
- [x] 10.4 `web/src/automation/payloadExport.ts`：Blob + object URL + `<a download>` 生成 `.json`，文件名 `${operationId || 'request'}-<timestamp>.json`（sanitize），revoke；preview 固定 `Not sent`、无 send/execute。Verify: 单测 mock createObjectURL/revoke；组件测试断言下载内容与 not-ready 禁用。
- [x] 10.5 e2e：上传 `fixtures/automation/openapi_sample.json` → Parse → 选 operation → 映射变量 → 下载 JSON（Playwright download）；并覆盖 template 更新流程：标记变量 → Save to template → 确认 → 卡片 version+1 → apply 使用新快照。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/automation-workbench.spec.ts --project=desktop`。
- [x] 10.6 文档与回归：更新 `how_to_use.md` / `web/README.md`（OpenAPI 子集、下载非发送、template 更新覆盖）；`fixtures/automation/openapi_sample.json`；pytest/vitest/typecheck/build/desktop e2e 全绿并记录数量。Verify: 全绿。

## 11. 下游系统配置 + mock send

- [x] 11.1 `fixtures/automation/downstream_systems.json` + `web/src/automation/downstreamSystemStore.ts`：schemaVersion、首次 seed 预设、`list/get/create/update/remove`、name/baseUrl(http(s)) 校验、最多 10 个、单 spec ≤ 512 KB、auth type/hint（不含 token）、损坏条目忽略、写失败 session-only。Verify: 单测覆盖 seed/CRUD/重载/全删不重种/上限/corrupt/quota/invalid URL。
- [x] 11.2 `Manage systems` UI：系统列表 + 新建/编辑/删除（两步确认）、name/baseUrl/environment/enabled/auth type+hint、spec 文件/粘贴 + Save、错误提示、`Saved in this browser — not on the server`；键盘与 aria-live。Verify: 组件测试覆盖 CRUD/空态/非法 URL/非法 spec/删除确认/写失败。
- [x] 11.3 Mapping 集成：system selector（显示 env/enabled）、选择系统自动 parse 绑定 spec、切换系统清空 operation/mapping 但保留 variables、删除选中系统清空 operation/mapping/receipt、无系统时 OpenAPI/mock send 不可用并说明。Verify: 组件测试。
- [x] 11.4 `web/src/automation/mockDownstreamSend.ts`：纯函数 200 `mock_success` / 500 `MOCK_DOWNSTREAM_ERROR`、endpoint=`baseUrl+path`、requestId、`now` 注入；无 fetch/token/history。Verify: 单测。
- [x] 11.5 `Send (mock)` UI：ready + enabled + operation 才可用；`Simulate failure` 默认关；receipt 显示 endpoint/status/requestId/payload 与 `Simulated — no network request`；不保存历史；Download 独立。Verify: 组件测试覆盖成功/失败/gating/label。
- [x] 11.6 e2e：创建/编辑系统并保存 spec → 选择系统 → 映射变量 → mock success → 打开 Simulate failure → mock 500 → reload 后系统仍在 → 删除确认。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/automation-workbench.spec.ts --project=desktop`。
- [x] 11.7 文档与全量回归：更新 `how_to_use.md` / `web/README.md`（系统配置、浏览器本地、mock send 非真实）；pytest/vitest/typecheck/build/desktop e2e 全绿并记录数量。Verify: 全绿。

## 12. Beneficiary matcher 修复

- [x] 12.1 `web/src/automation/mockWorkbench.ts` 的 `matchBeneficiary` 与 evidence 改为接受 `Beneficiary:` / `Beneficiary name:`（大小写、空白、全/半角冒号）；仍要求冒号+非空值，`{{...}}` 继续 missing。Verify: 单测覆盖 label variants、占位符、无冒号、普通提及。
- [x] 12.2 组件测试：选择 v2 mock template，正文 `Beneficiary name: aabbcc` → `beneficiary_name` 为 `matched`/`aabbcc` + evidence；confirm 后进入 payload。Verify: AutomationPanel 测试。
- [x] 12.3 全量回归：pytest / vitest / typecheck / build / desktop e2e 全绿并记录数量。Verify: 全绿。
- [x] 12.4 `matchExpiryDate` 日期规范化：接受 ISO、`YYYY/MM/DD`、`DD/MM/YYYY`、`DD/MM/YY`、`YYYY年MM月DD日`、英文月份名；统一输出 `YYYY-MM-DD`；DD/MM 默认、MM/DD 仅在第二段 >12；无效日历日期 missing。Verify: 单测覆盖 `12/03/27`→`2027-03-12`、各格式、无效日期。
- [x] 12.5 组件测试 + 文档 + 回归：v1 `Expiry date` 显示 `Confirm 2027-03-12`，confirm 后 payload 为 `"expiry_date": "2027-03-12"`；更新 `how_to_use.md` / `web/README.md` 的日期规范化说明；pytest/vitest/typecheck/build/e2e 全绿。Verify: 全绿。

## Workflow follow-up

- 归档顺序：`agent-knowledge` → `document-host-foundation` / `automation-run-core` → `automation-tab` → `automation-workbench-ui`。
- 后续 P1/P2 后端（服务端 template/downstream system 持久化与凭据、真实 HTTP 发送、extract/confirm、variables/occurrence、downstream mapping/payload）替换 mock adapter；本 change 只实现浏览器本地 template/系统、本地 OpenAPI 解析与不触网的 mock send，不声称服务端持久化或真实发送。
- 用模板新建 document/draft、跨文档复用/分享、Swagger 2.0/YAML/URL/oneOf·anyOf 支持、真实发送审计/幂等仍为后续 change。
- compare/rewrite/voice 仍为后续 change。