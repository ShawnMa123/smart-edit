# Proposal

## Why

后端已经有 `automation/run/result/accept/apply/undo`，但前端把唯一可用的 automation 面板放在版本栏底部；assistant 的 `Automation` tab 仍硬编码为 `implemented: false`，点击只显示 “Automation is not implemented in this build”。用户因此无法在预期位置发现或使用现有 run core。这个 change 只做 UI 集成，不新增 AI 能力，并把能力边界诚实标为 `fixture only`。

## What Changes

- `AssistantPanel` 增加 automation binding：`Automation` tab 从占位改为可用，显示 `Automation · fixture only`，不再标记 `not implemented`。
- 把 `AutomationFixturePanel` 从 `VersionPanel` 移到 Automation tab 内；版本栏只保留版本历史。
- Automation tab 展示：create fixture run、run status/stage、result outcome/completion/limitations、proposal preview、protected-fact risk acknowledgement、accept/apply/undo、run 取消与错误空态。
- 面板明确列出**未实现**能力：extract、compare、fill、真实模型改写、API mapping、voice；不得渲染示例答案或伪造模型结果。
- `Legal advice` 仍为 `not implemented`；`Rule audit` 与 `Knowledge Q&A` 保持现状。
- 更新 `AssistantPanel.test.tsx`、`AutomationFixturePanel` 测试、`web/e2e/draft.spec.ts`、`knowledge.spec.ts`、`errors.spec.ts` 与 `how_to_use.md` / `web/README.md`。
- **不改后端**：不新增 endpoint、不改变 run/apply/undo 合同、不接真实模型、不做 compare/extract/fill/mapping/voice。

## Capabilities

### New Capabilities

- `automation-workspace`: Automation tab 的可用性、fixture-only 标注、run 轮询、result/outcome 展示、proposal/apply/undo 交互、风险确认、错误与空态、可访问性；不覆盖后端生成能力。

### Modified Capabilities

- `document-editor`: assistant tabs 的要求从“knowledge/automation/legal 都标 not implemented”改为“knowledge 可用、automation 可用但仅 fixture、legal 仍 not implemented”。归档时必须排在 `agent-knowledge` 与 `document-host-foundation` 之后，避免旧 delta 覆盖。

## Impact

- **前端**：`web/src/components/AssistantPanel.tsx`、`AutomationFixturePanel.tsx`、`App.tsx`、`VersionPanel.tsx`、`styles.css`、`AssistantPanel.test.tsx`、`knowledge.spec.ts`、`errors.spec.ts`、`draft.spec.ts`、`how_to_use.md`、`web/README.md`。
- **后端**：无代码改动；复用 `POST /automation/runs`、`GET /automation/runs/{id}`、`GET /automation/results/{id}`、proposal accept/apply/undo。
- **数据/依赖**：0 个新依赖；不改变 host.db schema。
- **风险**：把“fixture-only”误读为完整 automation；必须在 tab 标签、banner、限制列表和文档中同时声明。`document-editor` 与未归档 `agent-knowledge` delta 有归档顺序依赖。