# Design

## Context

See `proposal.md`、`specs/automation-workspace/spec.md`、`specs/document-editor/spec.md`。

当前实现：

- `web/src/components/AssistantPanel.tsx` 的 `TABS` 把 automation 硬编码为 `implemented: false`，点击后只渲染通用 placeholder。
- `AutomationFixturePanel` 已有 run 轮询、result、accept/apply/undo、风险确认，但它通过 `VersionPanel` 的 `children` 渲染在版本栏。
- `App.tsx` 已有 `draft`、`lock`、`handleApplied`，可以直接传给 assistant pane。
- 后端已有 `/automation/runs`、`/results`、proposal decision/apply/undo；本 change 不改后端。

## Goals / Non-Goals

**Goals:**

- 把现有 automation run core 放到用户预期的 Automation tab。
- 用 `fixture only` 表达真实边界，Legal 保持 `not implemented`。
- 复用现有 `AutomationFixturePanel`，避免维护两套 automation UI。
- 保持版本栏只承担版本历史。
- 更新测试/e2e/docs，消除“有面板但 tab 说没实现”的矛盾。

**Non-Goals:**

- 不新增 extract/compare/fill/rewrite/mapping/voice。
- 不接真实模型、不新增 endpoint、不改变 apply/undo 合同。
- 不重做 assistant 的整体导航；只改 tab 状态与 automation 内容。
- 不把 fixture 结果说成模型或真实自动化。

## Decisions

### D1 用 `tab status` 取代 `implemented: boolean`

`Tab` 从：

```ts
{ id: 'automation', label: 'Automation', implemented: false }
```

改为：

```ts
type TabStatus = 'full' | 'fixture-only' | 'not-implemented';
{ id: 'automation', label: 'Automation', status: 'fixture-only' }
```

标签映射：

```
full            -> Audit / Knowledge Q&A
fixture-only    -> Automation · fixture only
not-implemented -> Legal advice · not implemented
```

替代：继续用 boolean + 特判 automation。会把“部分实现”硬塞进二元状态，后续 compare/extract 还要再改。

### D2 AssistantPanel 接收 automation binding

`AssistantPanelProps` 增加：

```ts
automation: {
  documentId: string;
  draft: DraftView | null;
  lock: LockView | null;
  onApplied: (view: DraftView) => void;
}
```

`App.tsx` 把已有 `draft`/`lock`/`handleApplied` 传入；`AssistantPanel` 在 automation tab 渲染 `AutomationFixturePanel`（建议重命名为 `AutomationPanel`，组件接口不变）。

替代：让 `VersionPanel` 继续渲染 automation 面板。会保留“入口错位”，不采用。

### D3 复用现有 AutomationFixturePanel，不复制逻辑

保留其 run 轮询、result/outcome、risk acknowledgement、accept/apply/undo 逻辑；只搬位置和改文案。组件内部继续使用 `web/src/api/automation.ts` 的 `createRun/getRun/getResult/...`。

组件需要：

- `draft` 为空时禁用 create，并说明“没有服务端草稿”；
- `lock` 为空时禁用 apply/undo，并说明锁不可用；
- run 失败/取消/超时时显示 status + error；
- `needs_clarification` / `unable_to_process` 不渲染 proposal；
- risk flags 非空时 apply 需要显式 checkbox。

### D4 Fixture-only 边界

Automation tab 顶部固定 banner：

```
Fixture-backed rewrite/replace_text only.
Not implemented: extract, compare, fill, model rewrite, API mapping, voice.
```

result limitations 也显示 `fixture_backed`。不得出现“model verified”“联网核实”等文案。

### D5 版本栏只保留版本历史

`VersionPanel` 删除 `children` prop（或保留但 App 不再传）；`App.tsx` 不再把 `AutomationFixturePanel` 放进版本栏。版本历史测试更新为不依赖 automation 面板。

替代：保留 children 作为通用插槽。会增加两个入口，容易再次错位，不采用。

### D6 错误与空态

- 没有 draft：Automation tab 显示“没有服务端草稿，无法创建 fixture run”，create 禁用。
- 没有 lock：显示“编辑锁不可用”，apply/undo 禁用。
- 创建 run 失败：显示 `code: message` 和重试按钮（Create fixture run）。
- 轮询失败：停止轮询，显示错误；不保留旧 proposal 作为本次结果。
- apply/undo 412/409：显示 conflict/undo_conflict，不清空编辑器内容。

### D7 可访问性

- tab 使用 `role="tab"` + `aria-selected`（现有）。
- run 状态使用 `aria-live="polite"`（现有 `run-status`）。
- 状态文本不只靠颜色。
- 所有动作是原生 button，键盘可达。
- risk checkbox 与文案关联。

### D8 测试与迁移

- `AssistantPanel.test.tsx`：Automation tab 可用、标签 `fixture only`、不再显示 `Automation is not implemented`；Legal 仍显示 not implemented。
- `AutomationFixturePanel.test.tsx`：现有 3 个测试保留，新增“移到 tab 后仍可创建/取消/result”。
- `web/e2e/draft.spec.ts`：fixture 流程改为在 assistant Automation tab 内完成。
- `web/e2e/knowledge.spec.ts` / `errors.spec.ts`：更新 Automation 标签/placeholder 断言；Legal 仍 not implemented。
- `how_to_use.md` / `web/README.md`：更新入口位置、fixture-only 边界、未实现列表。

### D9 归档顺序

`document-editor` 的 delta 修改的是 durable spec 中的 assistant tab 要求；`agent-knowledge` 与 `document-host-foundation` 尚未归档且也修改/新增相关能力。

归档顺序必须：

```
agent-knowledge
  -> document-host-foundation / automation-run-core
  -> automation-tab
```

否则旧的“knowledge/automation/legal 都 not implemented” delta 可能覆盖本 change 的修改。该顺序写入 tasks follow-up。

## Risks / Trade-offs

- [用户把 fixture-only 当成完整 automation] → tab 标签、banner、限制列表、result limitation、文档同时声明。
- [组件搬运导致 props 丢失] → 保持 `AutomationFixturePanelProps` 不变；App 只改渲染位置。
- [e2e 依赖旧标签] → 同步更新 knowledge/errors/draft specs；Legal 仍保留 not implemented 断言。
- [document-editor delta 与未归档 change 冲突] → 明确归档顺序；归档前检查 durable spec 的最终文本。
- [没有 draft/lock 时 UI 仍显示动作] → 禁用并解释，不用隐藏来伪装可用。

## Migration Plan

1. `AssistantPanel` 引入 `TabStatus` 与 automation binding；更新标签。
2. 把 `AutomationFixturePanel` 渲染从 `VersionPanel` 移到 automation tab；版本栏删除 children。
3. 更新 Vitest/Playwright 与文档。
4. 回滚：把组件放回 VersionPanel、恢复 boolean tab；不涉及后端/数据迁移。

## Open Questions

- 是否在本 change 把组件重命名为 `AutomationPanel`？建议是，但保留导出别名以免测试大改。
- 未来 compare/extract 进入同一个 tab 时，是否用子 tab（Extract / Compare / Rewrite）？本 change 不做，只预留 `Automation` tab 内的区域。
- `document-editor` durable spec 的归档顺序由谁执行？建议在归档前按 D9 检查。