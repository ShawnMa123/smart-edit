# Tasks

> 依据：`proposal.md`、`specs/automation-workspace/spec.md`、`specs/document-editor/spec.md`、`design.md`（D1–D9）。
> 边界：只改前端入口、标签、文案与测试；不改后端 endpoint、run/apply/undo 合同，不接真实模型。

## 1. Assistant tab 状态与 binding

- [x] 1.1 `web/src/components/AssistantPanel.tsx`：把 `Tab.implemented: boolean` 改为 `TabStatus = 'full' | 'fixture-only' | 'not-implemented'`；audit/knowledge 为 full，automation 为 fixture-only，legal 为 not-implemented。Verify: `AssistantPanel.test.tsx` 断言三个标签文案。
- [x] 1.2 `AssistantPanelProps` 增加 automation binding（documentId、draft、lock、onApplied），并在 automation tab 渲染 `AutomationFixturePanel`（或重命名后的 `AutomationPanel`）。Verify: 组件测试点击 Automation 后能看到 `Create fixture run`，不再显示通用 placeholder。
- [x] 1.3 `web/src/App.tsx`：把 `draft`/`lock`/`handleApplied` 传给 `AssistantPanel`；移除 `VersionPanel` 的 automation children。Verify: `App.test.tsx` 三栏不变；Automation tab 可操作。

## 2. 组件迁移与入口清理

- [x] 2.1 `web/src/components/VersionPanel.tsx`：删除 `children` prop 与渲染；`App.tsx` 不再把 automation 面板放进版本栏。Verify: `VersionPanel.test.tsx` 通过，版本栏无 `Create fixture run`。
- [x] 2.2 将 `AutomationFixturePanel` 重命名为 `AutomationPanel`（保留兼容导出或同步更新 import）；只搬位置，不改 run/apply/undo 逻辑。Verify: `AutomationFixturePanel.test.tsx`/`AutomationPanel.test.tsx` 仍覆盖 create/result/cancel。
- [x] 2.3 移除/更新旧的 `Automation is not implemented` 文案与测试断言；`Legal advice` 仍保留 not implemented。Verify: `AssistantPanel.test.tsx`、`web/e2e/knowledge.spec.ts`、`web/e2e/errors.spec.ts` 更新且全绿。

## 3. Automation tab 的状态、空态与边界

- [x] 3.1 无 draft/lock：create/apply/undo 禁用并显示原因；不显示伪造 proposal。Verify: 组件测试覆盖 `draft=null` 与 `lock=null`。
- [x] 3.2 run 失败/取消/超时：显示 terminal status + error；停止轮询；不把旧 proposal 当成本次结果。Verify: fake timers 测试覆盖 failed/cancelled/timed_out。
- [x] 3.3 result outcome：`proposal_ready` 显示 proposal + limitations；`needs_clarification` / `needs_handoff` / `unable_to_process` 只显示 outcome/details。Verify: 组件测试覆盖两种分支。
- [x] 3.4 Fixture-only banner 与未实现列表：固定显示 `Fixture-backed rewrite/replace_text only`，列出 extract/compare/fill/model rewrite/API mapping/voice 未实现；result limitations 显示 fixture_backed。Verify: 组件测试断言文案。
- [x] 3.5 risk acknowledgement：proposal 有 risk_flags 时 apply 需要 checklist；apply body 发送 acknowledged codes。Verify: 组件测试断言未勾选时禁用、勾选后调用 apply。
- [x] 3.6 可访问性：tab `aria-selected`、run status `aria-live`、状态文本不只靠颜色、动作键盘可达。Verify: 组件测试 + 手工键盘检查。

## 4. 端到端与既有页面

- [x] 4.1 `web/e2e/draft.spec.ts`：fixture 流程改为在 assistant Automation tab 内 create run → poll → accept/apply/undo。Verify: `PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/draft.spec.ts --project=desktop`。
- [x] 4.2 `web/e2e/knowledge.spec.ts`：Automation tab 标签为 fixture-only，knowledge 仍可用；移除旧 not implemented 断言。Verify: knowledge spec 通过。
- [x] 4.3 `web/e2e/errors.spec.ts`：Legal 仍 not implemented；Automation 不再显示 generic placeholder。Verify: errors spec 通过。
- [x] 4.4 `web/e2e/layout.spec.ts` / narrow 视图：Automation tab 在窄屏可切换且可操作。Verify: 对应 e2e 通过。

## 5. 文档与验收

- [x] 5.1 `how_to_use.md`：更新 Automation 入口位置、fixture-only 边界、未实现列表、apply/undo 风险确认。Verify: 文档步骤与组件测试一致。
- [x] 5.2 `web/README.md`：更新 assistant tab 说明，删除“Automation 仍 not implemented”的旧描述，保留 Legal not implemented。Verify: 文档中的标签与 UI 一致。
- [x] 5.3 全量回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`typecheck`、`build`、`PW_CHANNEL=chrome npm --prefix web run e2e -- --project=desktop`。Verify: 全绿并记录测试数量。

## Workflow follow-up

- 归档顺序：`agent-knowledge` → `document-host-foundation` / `automation-run-core` → `automation-tab`；归档前检查 `document-editor` durable spec 的最终文本。
- compare/extract/fill/真实模型/API mapping/voice 仍为后续 change，不在本次范围。
- 若未来 Automation tab 增加子 tab（Extract/Compare/Rewrite），保留本 change 的 fixture-only banner 作为当前能力声明。