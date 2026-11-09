# Demo record — editor-shell

Acceptance evidence for tasks 8.1–8.4. Artifacts are English per an explicit instruction
(`design.md` Open Questions 1).

## What was run

```bash
# backend (fixture provider) — the path that produces real field checks
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
  .venv/bin/uvicorn app.api.main:app --port 8010

# frontend checks
npm --prefix web install
npm --prefix web run typecheck     # tsc --noEmit == clean
npm --prefix web run test          # vitest (jsdom + node) == 89 passed, 2 guarded e2e skipped
npm --prefix web run build         # emits web/dist/index.html

# acceptance over real HTTP (needs the backend above)
VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.audit.test.ts
```

## 8.1 Fixture-provider audit (real HTTP)

```
E2E digest: 9dfc42376d25 | stages: parse:done extract:done normalize:done
Tests  1 passed | 1 skipped (2)
```

Asserted from the returned envelope and the view model the panel renders: stage order
`parse → extract → normalize`, `digest` equal to the snapshot taken before the request,
`stale = false`, `usedFixture = true`, `fieldChecks = "ran"`, non-empty `checks`, at least one
`extracted` field, and `resultLabel = "No findings in the checks that ran"` (never "pass").

## 8.2 Honesty path (no `SMART_EDIT_LLM`)

```
Honesty path: did-not-run | no model provider configured (set SMART_EDIT_LLM) | Field checks did not run
Tests  1 passed | 1 skipped (2)
```

With the provider unset the backend still returns `parse: done`, `extract: failed`,
`normalize: done`; the view model refuses to treat the placeholders as document defects:
`fieldChecks = "did-not-run"`, `blockedReason` = the stage reason, `checks = []`.

## 8.3 Prototype parity checklist

Reference: `tradeAI_requirementDesign_v2/HSBC_Nexus_Document_Editor_Mock_Demo.html`, function
`auditPanel()` (idle / running / failed / report + `reportStale()`).

| Mock behaviour | This build | Status |
|---|---|---|
| Three-column grid `208px minmax(320px,1fr) 352px` | `web/src/styles.css` `.work-grid` uses exactly that template | same |
| Narrow viewport switches panes with tabs | `useViewport` + `.pane-tabs` (`max-width: 1365px`) | same |
| Left pane: version list + compare + document info | Version list with label/digest/time/chars; compare present but disabled and labelled "not implemented" | same + disclosure |
| Assistant tabs: knowledge / automation / audit / legal | Same four tabs; only audit wired; the rest labelled "· not implemented" and render no content | same + disclosure |
| Idle: scope notice ("本次范围") + run button | `ScopeBlock` (checks that ran / not run) above the `Run spec audit` button | same intent |
| Running: "固定快照已捕获" + cancel | "Fixed snapshot captured", audited digest, elapsed timer, "Stop waiting" | same + disclosure that it only stops waiting client-side |
| Failed: "审计执行失败 … 未生成通过结论" | "Audit failed — no conclusion produced", message from `code`, elapsed, retry | same intent |
| Report: pass/fail tag + metrics + findings | Outcome chip (`Checks ran` / `Checks did not run` / `Stale report`) + counts by field status and finding severity | different shape — deviation 1 |
| Report: stale banner + "基于当前快照重新审计" | "Report is stale … cannot be used for approval" + "Re-audit current snapshot"; previous findings stay readable | same |
| Report footer: "无命中不代表合法合规" | "No findings does not mean the document is compliant. Jurisdictional applicability was not assessed." + digest, noted as browser-computed | same intent |
| One fixed semantic sample finding ("语义样例") | Not rendered — semantic checks are named as *not run* in the scope block | deliberate deviation 2 |
| `contenteditable` rich-text document | Plain-text `<textarea>` page | deliberate deviation 3 |
| Version hash that is random | SHA-256 of the exact text via Web Crypto, shown per version | improves on the mock |

### Deviations, with reasons

1. **Metric shape.** The mock shows "deterministic checks passed 2/3". The backend reports per-field
   statuses, not a rule score; inventing a denominator would be a fabricated metric, so counts per
   status and per severity are shown instead.
2. **No semantic sample finding.** Rendering a pre-written semantic warning is exactly the fabricated
   finding `Requirements.md` §14 lists as a gap. The scope block states semantic checks (RULE-02)
   did not run.
3. **Plain text instead of rich text.** Design D3: the audit consumes text, and a `contenteditable`
   surface silently rewrites quotes/spaces/paragraph breaks. Formatting is labelled unimplemented.
4. **Layout parity is structural, not pixel.** Grid template, pane order and breakpoint are asserted
   in `web/src/App.test.tsx`; jsdom performs no layout, so one human pass remains (checklist below).

### Manual pass still to do (5 minutes, human eyes)

- [ ] At 1366×768: three panes visible, editor column widest, no horizontal scrollbar
- [ ] Narrow the window under 1366 px: pane tabs appear, one pane at a time
- [ ] Click `Run spec audit` with the fixture backend: stage strip green, checks table fills, shown
      digest matches the one printed at run start
- [ ] Edit one character after a report: stale banner appears and findings remain visible
- [ ] Select a non-audit tab: it states "not implemented" and shows nothing fabricated
- [ ] Keyboard only: tab through versions → editor → assistant and activate the audit action

## 8.4 Artefacts

| Item | Value |
|---|---|
| Fixture provider | `SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json` |
| Sample document | `fixtures/llm/sample_document.txt` |
| Text digest observed (8.1) | `9dfc42376d25…` (SHA-256 of the exact UTF-8 text) |
| Stage statuses (8.1 / 8.2) | `parse:done extract:done normalize:done` / `parse:done extract:failed normalize:done` |
| Frontend checks | `typecheck` clean · `test` 89 passed (+2 guarded e2e skipped by default) · `build` emits `web/dist/index.html` |
| Backend suite | `.venv/bin/python -m pytest -q` → 117 passed (unchanged by this change) |