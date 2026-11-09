# Tasks

> Planning artifacts are English per an explicit instruction (see `design.md` Open Questions 1).
> This change adds `web/` only: it must not modify `app/state.py`, the node signatures, or any
> `console-api` contract.

## 1. Transport probe (blocking)

- [x] 1.1 Confirm the three endpoints this UI depends on actually respond: start
  `uvicorn app.api.main:app`, then `POST /runs` with `{text}`, `POST /runs/{thread_id}/stages/normalize`,
  `GET /runs/{thread_id}`. Verify: captured probe output showing `thread_id`, an envelope containing
  `stages`, `fields`, `findings`, `trail`, `supported_stages`. **If any endpoint is missing, stop and
  raise the fallback decision (absorb the API work into this change) before starting group 2.**
- [x] 1.2 Record the base URL and proxy assumption in `web/README.md`. Verify: the documented port pair
  matches `vite.config.ts` and the uvicorn command in the README.

## 2. Web project scaffolding

- [x] 2.1 Create the Vite + React + TypeScript project in `web/` with `strict` TypeScript and scripts
  `dev`, `build`, `typecheck`, `test`. Verify: `npm --prefix web run build` emits `web/dist/index.html`
  and `npm --prefix web run typecheck` exits 0.
- [x] 2.2 Layout shell: CSS grid `208px minmax(320px, 1fr) 352px` at ≥1366 px, a three-way tab switcher
  below that breakpoint, semantic `aside` / `section` / `aside` landmarks. Verify: component test
  asserting all three panes are present at a wide viewport and exactly one is shown at a narrow one,
  plus DOM order versions → editor → assistant.
- [x] 2.3 Design tokens for status treatment (text label + colour) and a visible `:focus-visible` style.
  Verify: token module exists and its unit test lists a label for every status value used by the app.

## 3. Domain modules

- [x] 3.1 `web/src/snapshot.ts`: `createSnapshot(text, versionId)` → `{text, digest, versionId,
  capturedAt}` with `digest` = SHA-256 hex of the UTF-8 bytes. Verify: vitest — same text yields the
  same digest, one changed character yields a different one, and a multi-byte (CJK) sample digests
  deterministically.
- [x] 3.2 `web/src/versionStore.ts`: `localStorage`-backed capture / list / restore / clear keyed by a
  stable `documentId`, newest first, capped at 20. Verify: vitest with a fake storage — capture grows
  the list, restore never mutates an entry, the cap evicts the oldest, `clear` empties it.
- [x] 3.3 `web/src/auditMachine.ts`: reducer with `idle | running | failed | report`, plus a `stale`
  flag derived from `report.digest !== currentDigest`. Verify: vitest covering each transition and the
  case "edited while running" — the report stays bound to the audited digest and turns stale.

## 4. Transport client

- [x] 4.1 `web/src/api/client.ts`: `createRun`, `triggerStage`, `getRun`; 120 s `AbortController`
  deadline; non-2xx and transport failures throw `ApiError {status, code, message, detail}`. Verify:
  vitest mapping a success envelope, a 409 body onto `code`, and an aborted request onto a timeout
  `ApiError`.
- [x] 4.2 `web/src/api/errors.ts`: `explainError(code)` for `unknown_stage`, `REFUSED`,
  `NOT_STANDALONE`, `unknown_run`, `EMPTY_SUBMISSION`, `INCOMPLETE_RESULT` plus a fallback. Verify:
  vitest iterates every code and asserts a distinct, non-empty message; an unknown code falls back
  without inventing a cause.
- [x] 4.3 `web/src/api/envelope.ts`: a guard that rejects a 200 response whose body lacks `stages`.
  Verify: vitest — a body without `stages` produces an error state, never a usable envelope.

## 5. Audit view model (the honesty gate)

- [x] 5.1 `web/src/auditView.ts`: `(envelope, snapshot, currentDigest)` → view model with
  `fieldChecks: "ran" | "did-not-run"`, `blockedReason`, `scopeRan`, `scopeNotRun`, `checks`,
  `countsPerSeverity`, `resultLabel`, `stale`. Verify: vitest with three envelopes — extraction failed,
  extraction done with findings, extraction done with none.
- [x] 5.2 A non-`done` extraction stage yields `fieldChecks: "did-not-run"` with the stage `reason`, and
  `checks` MUST be empty. Verify: vitest asserting exactly that, plus a second case where `partial`
  behaves the same.
- [x] 5.3 Scope lists are explicit constants: ran = required presence, value format, length; not run =
  semantic consistency, template clauses, regulatory coverage. Verify: vitest asserts both lists are
  non-empty and that the not-run list names all three unimplemented check families.
- [x] 5.4 Zero findings produce `resultLabel` meaning "no findings in the checks that ran" — never
  "pass" or "compliant". Verify: vitest asserting the label text and that no "pass" wording appears.
- [x] 5.5 Fixture-backed extraction is surfaced: when the `extract` reason mentions a fixture, the view
  model exposes `usedFixture: true`. Verify: vitest for both fixture and provider envelopes.

## 6. The three panes

- [x] 6.1 `VersionPanel` (left): version list newest first showing label, digest (short form), creation
  time and character count; actions capture / restore / clear-history; a compare control present but
  disabled and labelled "not implemented". Verify: component tests for list rendering, restore, and the
  disabled compare control.
- [x] 6.2 `EditorColumn` (centre): textarea styled as a document page, character count, unsaved-change
  marker, soft warning above 50,000 characters, and the capture/snapshot affordance in the footer.
  Verify: component test — typing marks unsaved, capturing clears it and appends a version.
- [x] 6.3 `AssistantPanel` (right): header, the four tabs (`audit`, `knowledge`, `automation`,
  `legal`), audit tab selectable, the other three disabled and labelled "not implemented in this
  build", footer note about fixed snapshot and human decision. Verify: component tests, including that
  selecting a disabled tab renders no sample answer, finding or citation.
- [x] 6.4 Document header/footer actions from the prototype (format, import, export, approve) are
  present but labelled unavailable, and activating one reports "unavailable". Verify: component test
  asserting every such control is labelled and none reports success.

## 7. Audit panel states

- [x] 7.1 Idle: empty state with the scope disclosure and a primary `Run spec audit` action. Verify:
  component test asserting the scope block is visible without opening a dialog.
- [x] 7.2 Running: elapsed timer, the frozen snapshot digest, and a wait-cancel that states it only
  stops waiting client-side. Verify: component test with fake timers asserting the timer and the
  wording.
- [x] 7.3 Failed: message derived from `code`, elapsed time, retry action. Verify: component tests for
  a 409 refusal and for a timeout, asserting no pass state appears.
- [x] 7.4 Report: stage strip (stage / status / reason), check list with field status, notes and source,
  findings with severity / evidence / field keys, per-severity counts, the audited digest, and the
  standing "no findings is not compliance" note. Verify: component test driven by a fixture envelope.
- [x] 7.5 Stale: banner stating the report is bound to an older snapshot and cannot be used for
  approval, previous findings still readable, and a re-audit action. Verify: component test that
  mutates the document after a report and asserts the banner plus retained findings.
- [x] 7.6 Fixture banner: a fixture-backed report shows a visible stub notice naming the fixture.
  Verify: component test for the fixture envelope only.
- [x] 7.7 Accessibility assertions: every status chip renders a text label, and the panes, tabs and
  audit action are reachable by keyboard in DOM order. Verify: component test scanning rendered chip
  text and asserting tab order.
- [x] 7.8 Rule audit block: `App` triggers `stages/audit` after `normalize` and the panel renders
  `verification` — one `Issue` per planned unit, the coverage ratio, the audited findings with their
  `gate_type` / `target_operations`, and the gate decision. Absent report and absent gate decision each
  get their own word (`Rule audit did not run`, `Not asked`) so neither can read as clean/allowed.
  Verify: component test for both states, and the guard that the audit is never requested unless
  `extract` **and** `normalize` are `done` (`fieldChecksRan()` in `auditView.ts`).

## 8. Acceptance

- [x] 8.1 End-to-end audit over HTTP with the fixture provider: capture a snapshot, run `normalize`, then
  `stages/audit`, and assert the panel shows the stage strip (`parse/extract/normalize/audit`), checks,
  counts, the rule-audit block (**51 planned / 33 assessed / ratio 0.647 / `no_findings` / gate
  `not-asked`**) and the audited digest. Verify: `src/e2e.audit.test.ts` against a live backend
  (`VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010`), recorded in `DEMO.md`.
- [x] 8.2 Honesty path end-to-end: with `SMART_EDIT_LLM` unset, the panel shows "field checks did not
  run" with the stage reason, no defect list, **and** "rule audit did not run" — the UI never sends
  placeholders to `/stages/audit`. Verify: `VITE_E2E_HONESTY=1` recorded result in `DEMO.md`.
- [x] 8.3 Prototype parity checklist: idle / running / failed / report / stale states compared against
  `HSBC_Nexus_Document_Editor_Mock_Demo.html`, plus the layout comparison at 1366×768. Verify: every
  line of the checklist in `DEMO.md` ticked, or the deviation recorded with its reason.
- [x] 8.4 Write `openspec/changes/editor-shell/DEMO.md`: commands used, `SMART_EDIT_LLM` value, the
  digests observed, the stage statuses, and the honesty-path output. Verify: the file exists and its
  numbers match the runs from 8.1 and 8.2.

## Workflow follow-up

- Trim `frontend-console` to its API-only portion (or archive its UI capability) so the repo holds one
  UI plan; this shell supersedes its console screen.
- Decide Open Question 1 (`openspec/config.yaml` still declares `zh` while these artifacts are
  English) — the flip affects all three owners.
- When server-side versions (VER-01/VER-03) land, replace `localStorage` history and the client digest
  with the server's transactional snapshot and deterministic digest; the snapshot shape already
  anticipates it.
- **Spec sync (2026-11-09):** `rich-text-editor` delivered the TipTap surface and `document-import`
  made file import real. `specs/document-editor/spec.md` now separates the actions this build can
  perform (formatting, import) from the ones it still cannot (export, approval), and `design.md`
  marks D3 as superseded. Nothing else in this delta changed.
- Archive this change with `/opsx-archive` once 8.3 has been demonstrated against the prototype.