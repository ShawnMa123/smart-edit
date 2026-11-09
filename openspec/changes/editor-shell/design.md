# Design

## Context

See `proposal.md` — Why. What shapes the approach:

**Sources.** `tradeAI_requirementDesign_v2/Requirements.md` §5 (online editing), §6 (locks, drafts,
versions), §8 (knowledge assistant), §9 (spec audit + regulatory advice), and
`HSBC_Nexus_Document_Editor_Mock_Demo.html` as the layout/behaviour reference. The prototype is
explicitly *not* a specification of behaviour: §14 lists where it fakes (fixed four findings, random
version hash, results that survive document edits, `contenteditable`), so the mock is followed for
**structure and states**, never for data or conclusions.

**Reference structure** (measured in the mock): `.work-grid` with
`grid-template-columns: 208px minmax(320px, 1fr) 352px`; left `aside.sidebar` = version history +
compare slot + document-info footer; centre `section.editor-column` = lock line, document body,
footer with save/submit; right `aside.assistant` = header, four tabs (`knowledge` / `automation` /
`audit` / `legal`), body, and a footer note about fixed snapshot + traceable sources. Its
`auditPanel()` has exactly four states — idle, running, failed, report — plus a `stale` flag, and its
honesty strings ("本次范围", "无命中不代表合法合规", "结果已过期 · 审批不能使用旧结果") are the
pattern this design keeps.

**Backend reality.** `agent-normalize` is implemented (`parse` / `extract` / `normalize`, plus
`app/standalone.py::plan_standalone`). There is no graph, no checkpointer, no `app/api/`, and no model
provider. The HTTP transport is specified in `frontend-console/specs/console-api/spec.md`:
`POST /runs`, `POST /runs/{thread_id}/stages/{stage}`, `GET /runs/{thread_id}`, error `code`s, and an
envelope that always carries `stages`.

**Contract.** `app/state.py` is frozen: the editor consumes `FieldValue`, `Finding`, `StageReport`,
`TrailEntry` as they are; it adds no state key and changes no agent output.

**Non-functional constraints from §13** that bind the UI: 1366×768 baseline, keyboard operable,
status never conveyed by colour alone, 120 s review timeout surfaced explicitly.

## Goals / Non-Goals

**Goals:**

- A runnable three-pane workspace whose audit is a real round trip to `agent-normalize`, bound to an
  immutable snapshot.
- One place (`auditView.ts`) that decides what may be claimed, so "extraction never ran" cannot be
  rendered as "your document is missing seven fields".
- Version history that is honest about being browser-local, and that never rewrites itself.
- Zero backend change and zero new endpoint: the editor is a client of `console-api`.
- A layout close enough to the prototype that reviewers can compare side by side.

**Non-Goals:**

- Rich-text editing/formatting (ED-02), import of DOCX/PDF/images and OCR (ED-03/04/05).
- Server locks, drafts, versions, digests, approval workflow, notifications (§6.1, §10).
- Structural version diff/compare (VER-04) — the compare control is shown disabled and labelled.
- Knowledge, automation and legal assistant tabs (§8, §9.2) — present but labelled unimplemented.
- Semantic checks (RULE-02), template rule packs (RULE-03), regulatory coverage — disclosed as not
  run, never simulated.
- Multi-user/CRDT collaboration, server-side session, authentication.

## Decisions

### D1. Audit is two calls on the existing transport; no new endpoint

`Run spec audit` → `POST /runs` with `{text}` → `POST /runs/{thread_id}/stages/normalize` → render the
returned envelope. `GET /runs/{thread_id}` is used only for a manual refresh.

*Why:* `console-api` already accepts text and already returns the envelope including `stages`; adding
an `/audit` endpoint would duplicate run creation and force a second delta on a capability this
change does not own. *Alternatives:* (a) a dedicated audit endpoint — better naming, but two owners
for one flow and a guaranteed archive-time collision; (b) call `POST /runs` only and hope the server
runs the full chain — the transport does not promise that, so the client would depend on unstated
behaviour.

### D2. The snapshot digest is computed in the browser

Snapshot = `{ text, digest: SHA-256(text) as hex, versionId, capturedAt }`, digest via Web Crypto over
the UTF-8 bytes of the exact text.

*Why:* it needs no server change, it exists *before* the request (so the panel can name the digest it
is about to audit), and it is what makes staleness detection instant on the next keystroke.
*Alternatives:* (a) have the server return a digest — requires an API change and still cannot detect
edits made while the request is in flight; (b) skip digests and compare full text — works for
staleness but cannot be displayed as a stable identifier. **Caveat, disclosed in the UI:** a
client-side digest is not tamper-evident and is not the server-side deterministic digest VER-03
requires; it identifies *which text this browser sent*, nothing more.

### D3. The editor is a plain-text document surface

A `<textarea>` styled as a document page, with character count, unsaved-change marker, and
snapshot/submit affordances in the column footer.

*Why:* the audit's input is text and exact fidelity is the whole point — a `contenteditable` surface
(what the mock uses) silently converts quotes, non-breaking spaces and paragraph breaks, exactly the
corruption class `normalize_ws` had to be built to survive. A textarea also gives keyboard behaviour
and screen-reader semantics for free. *Alternatives:* (a) TipTap + Yjs per §11 — real editing, but
CRDT, schema and anchor work belongs to a later phase and would dwarf this change;
(b) `contenteditable` — cheap imitation of the mock, expensive to trust.

### D4. Version history lives in `localStorage`, append-only

Entries `{id, label, digest, createdAt, chars, text}`, newest first, capped (default 20). Restore loads
text into the editor as an unsaved draft; capturing again creates a **new** entry. A stable
`documentId` keeps history across reloads.

*Why:* there is no server version store, and keeping versions only in component state (the mock's
approach) loses them on reload — the demo would then be indistinguishable from the prototype it is
supposed to improve on. *Alternatives:* IndexedDB (more code, no gain at this size); server versions
(VER-01/03 territory, out of scope). **Caveat, disclosed:** history is per-browser, unsigned, and held
on the operator's machine.

### D5. Audit state is a pure reducer, not a pile of booleans

`web/src/auditMachine.ts`: `idle → running → (report | failed)`, plus a `stale` flag derived from
`report.digest !== currentDigest`. Every transition is a function of `(state, event)`.

*Why:* the mock tracks the same thing with `runBusy`, `state.reports[user]` and `reportStale()`
scattered across handlers, which is how "old report shown next to new text" bugs survive review. A
reducer makes the honesty rule testable in isolation and makes impossible states unrepresentable.
*Alternatives:* component-local `useState` (unde­buggable combinations), React Query (network
caching, not a state machine for a claim).

### D6. One view-model module decides what may be claimed

`web/src/auditView.ts` maps `(envelope, snapshot, currentDigest)` → a view model carrying
`fieldChecks: "ran" | "did-not-run"`, `blockedReason`, `scopeRan[]`, `scopeNotRun[]`,
`countsPerSeverity`, `checks[]`, `stale`. Components render that model and make no judgements.

*Why:* the failure this design most needs to prevent — "extract never ran, so every field is
`missing`, so the panel accuses the customer's document" — becomes a single tested branch instead of a
JSX condition repeated in four places. *Alternatives:* guard clauses inside components (spread thin,
easy to regress during a demo fix); a server-provided summary (the transport returns the envelope, not
an interpretation, and `console-api` is not ours to extend).

### D7. Error copy is derived from `code`

`explainError(code)` covers `unknown_stage`, `REFUSED`, `NOT_STANDALONE`, `unknown_run`,
`EMPTY_SUBMISSION`, `INCOMPLETE_RESULT`, plus a fallback; the server `message` is shown as detail.

*Why:* `console-api` promises clients branch on `code`, and prose changes between builds while codes
do not. *Alternatives:* render `message` directly (breaks the moment a message is reworded, and shows
English server text where the pane expects a specific explanation).

### D8. Layout and accessibility follow the prototype, with text labels

Grid `208px minmax(320px, 1fr) 352px` at ≥1366 px; below that, a three-way tab switcher across the
same panes. Every status chip carries a word plus colour; focus is visible; panes and tabs are
keyboard reachable in DOM order (versions → editor → assistant).

*Why:* §13 makes the 1366×768 baseline, keyboard operation and "not colour alone" hard requirements,
and the mock already ships the responsive tab switcher. *Alternatives:* a component library with a
ready-made grid (extra dependency, and the visual target is a specific prototype); colour-only chips
(fails §13 and fails for colour-blind reviewers).

### D9. The 120-second limit is enforced client-side and disclosed

The audit request runs under an `AbortController` with a 120 s deadline (§13). On expiry the panel
shows a timeout failure with elapsed time and states that the run may still be finishing on the
server; retry is offered.

*Why:* without a server-side cancel in `console-api`, the only honest client behaviour is to stop
waiting and say so. *Alternatives:* wait indefinitely (a hung request looks like a slow audit);
pretend cancellation (the server keeps working — a lie the UI would have to keep).

### D10. The transport is isolated behind one module

All HTTP lives in `web/src/api/` (`createRun`, `triggerStage`, `getRun`), returning typed results and
throwing `ApiError { status, code, message, detail }`. Nothing else in the app calls `fetch`.

*Why:* this change depends on `console-api` landing. With one seam, a demo can substitute a local mock
server by swapping a module, and — if the transport is deprioritised — absorbing the API work into this
change is a known, sized option instead of a mid-demo discovery. *Alternatives:* call `fetch` from the
components (harder to substitute, easy to bypass the error contract).

## Risks / Trade-offs

- **[The transport may not exist]** → This change calls endpoints specified only in
  `frontend-console/specs/console-api/spec.md`, which is unimplemented. Mitigation: D10 isolates HTTP,
  and the first task group verifies the three endpoints respond before any UI work starts. If that
  change is deprioritised, the fallback is explicit — absorb the API work here and record the
  supersession, rather than keep a UI nobody can run.
- **[Placeholders read as defects in the customer's document]** → Gated in `auditView.ts` (D6): a
  non-`done` extraction stage yields "field checks did not run", never a defect list. Tested as a unit
  case, not as a rendering detail.
- **[Fixture-backed extraction mistaken for a real model run]** → The `extract` stage `reason` is
  surfaced verbatim in the panel, with distinct styling and wording that names the fixture.
- **[Client digest mistaken for a tamper-evident digest]** → The UI labels it as computed in this
  browser, and both proposal and design state it is not VER-03's server-side digest.
- **[`localStorage` holds customer document text]** → History is capped (20 entries), the pane states
  it is browser-local, and one action clears it. Demo machines should not be shared with real customer
  material; noted for the demo checklist.
- **[Two UI plans in one repo]** → `frontend-console`'s console UI is superseded by this shell; a
  follow-up trims that change to the API-only portion so nobody builds both screens.
- **[Prototype parity drifts silently]** → Acceptance compares this shell against the mock's panel
  states (idle / running / failed / report / stale) as a written checklist, not as pixel snapshots.
- **[Long documents stress the flow]** → §13's 50,000-character guidance is shown as a soft warning;
  elapsed time is always visible; the 120 s abort prevents an indefinite "running" claim.
- **[A plain textarea looks like a downgrade from the prototype]** → Accepted deliberately (D3):
  exact text beats imitation rich text, and the missing formatting is labelled as not implemented
  rather than faked.

  **Superseded (2026-11-09):** `rich-text-editor` replaced the textarea with the TipTap surface and
  `document-import` made file import real, so the delta now separates the actions this build can
  perform (formatting, import) from the ones it still cannot (export, approval). D3 survives only as
  the reason the editor shipped as plain text first.

## Migration Plan

Purely additive: new `web/` application, no backend change, no frozen file touched.

1. Prerequisite: the three `console-api` endpoints respond (verify first — see Risks).
2. `npm --prefix web ci && npm --prefix web run dev` for development, proxying `/api` to
   `uvicorn app.api.main:app`. If that API layer does not mount `web/dist`, the built SPA can be served
   by any static server for the demo; the proxy is the only coupling.
3. Optional demo provider: `SMART_EDIT_LLM=fixture:<path>` gives an end-to-end audit without a key;
   with it unset the panel demonstrates the honest "field checks did not run" path instead.
4. Rollback: delete `web/`. Nothing else references it.
5. After landing: trim `frontend-console` to the API-only portion (or archive its UI capability), so
   the repo holds one UI plan.

## Open Questions

1. **Artifact language.** These artifacts are English per an explicit instruction while
   `openspec/config.yaml` still declares `Language: zh`. Flipping that line affects all three owners,
   so it stays a team decision rather than a change inside this planning change.
2. **Which fixture file backs the demo.** `SMART_EDIT_LLM=fixture:<path>` needs one agreed fixture;
   `agent-normalize` owns the fixture directory, so the path is picked there and referenced here when
   the demo is scripted. Deferrable — it changes no spec and no task shape.
3. **Server-side versions later.** VER-01/VER-03 (transactional versions, server-side deterministic
   digest) will eventually replace `localStorage` history; that is a separate change, and this
   design's snapshot shape anticipates it (`digest` + `versionId` + `capturedAt`).
4. **Keeping the prototype in the repo.** Whether the 200 KB mock HTML stays as the visual reference
   after this change lands, or moves to a design archive. No behavioural impact either way.