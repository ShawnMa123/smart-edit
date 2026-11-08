# Proposal

## Why

`tradeAI_requirementDesign_v2/Requirements.md` and the HTML prototype it annotates describe a
three-pane workspace — version history, document body, AI assistant — in which an operator edits a
guarantee, snapshots it, and asks for rule checks. None of it runs today: the prototype is a 200 KB
static file whose audit is faked (`固定四条审查意见`, random version hashes, `contenteditable`), and
`Requirements.md` §14 lists exactly those fakes as the gaps to close. Meanwhile the one capability
that is actually implemented — `agent-normalize` — already produces the deterministic field evidence
a spec audit needs (required-field presence, `extracted` / `inferred` / `missing`, `N-` truncation
findings), and there is no screen anywhere that can point it at a document.

So: build the runnable shell, wire its audit button to `agent-normalize` over the transport already
planned as `console-api`, and make every capability this build does not have visible on screen
instead of simulated.

## What Changes

- **New three-pane workspace** (`web/`): version history (left), document editor (centre), AI
  assistant (right). Column geometry and panel states follow
  `HSBC_Nexus_Document_Editor_Mock_Demo.html` (`208px minmax(320px, 1fr) 352px`; version list +
  compare slot; editor footer with snapshot/submit; assistant tabs with `规则审计` selected).
- **`Run spec audit` button** in the audit tab: capture the current document snapshot (text +
  SHA-256 digest + version id) → `POST /runs` → `POST /runs/{thread_id}/stages/normalize` → render
  the returned checks. No other endpoint is added.
- **Audit result panel** containing: a scope disclosure of what was actually checked, a stage strip,
  the deterministic check list derived from `fields` (`missing` / `inferred` / `notes`) and `N-`
  findings, per-status counts, the snapshot digest the report is bound to, a staleness marker when
  the document changes afterwards, and the "no findings is not compliance" footnote.
- **Result gating on stage status**: when `extract` did not complete (for example no model provider
  is configured), the panel MUST state that field checks did not run, and MUST NOT present
  `missing` placeholders as defects in the customer's document.
- **Browser-local version history**: snapshot on demand, list with digest and timestamp, restore
  into a new draft (history is never rewritten). No server-side version store, no lock, no CRDT.
- **Supersedes the UI planned by `frontend-console`**: that change's `console-api` transport is
  consumed unchanged (no delta here); its single-screen console is replaced by this shell.

**Out of scope** (each labelled as unimplemented in the UI): rich-text formatting and toolbar
(ED-02), DOCX/PDF/image import and OCR (ED-03/04/05), server edit locks, approval workflow and
handover (§6.1, §10), structural version diff (VER-04), the knowledge / automation / legal assistant
tabs (§8, §9.2), semantic checks (RULE-02), template rule packs (RULE-03), regulation coverage
(§9.2), and multi-user collaboration.

**BREAKING**: none — nothing existing is removed; only new files are added.

## Capabilities

### New Capabilities

- `document-editor`: the three-pane editing workspace and its audit round trip — how a document is
  edited and snapshotted, what the audit request sends, how results are presented and scoped, how
  staleness is decided, and what the screen must never claim.

### Modified Capabilities

None. `openspec/specs/` holds no archived capability yet, and the HTTP transport is consumed from
`frontend-console/specs/console-api/spec.md` without change — creating a second `console-api` delta
here would collide with that capability when both changes archive.

## Impact

- New `web/` application (Vite + React + TypeScript). Shares no code with `frontend-console`'s
  planned UI, which this change supersedes.
- Depends on three endpoints from the `console-api` delta: `POST /runs`,
  `POST /runs/{thread_id}/stages/{stage}`, `GET /runs/{thread_id}`.
- Reads only the frozen `app/state.py` contract (`FieldValue` / `Finding` / `StageReport` /
  `TrailEntry`); no backend file is modified here.
- New browser dependencies: React + Vite only. SHA-256 comes from Web Crypto; snapshots live in
  `localStorage`.
- **Risk (sequencing):** if `frontend-console`'s transport never lands, the audit button has nothing
  to call. Mitigation is in `design.md` — the dependency is isolated behind one client module and the
  fallback (this change absorbing the API work) is called out rather than discovered mid-demo.
- **Risk (false accusation):** a panel showing "7 required fields missing" when extraction never ran
  would blame the customer's document for our missing model key. The stage-gating requirement above
  exists specifically to prevent it.
- **Acceptance anchor:** the `Requirements.md` §14 gap table is the checklist for what this shell
  must admit it does not do; anything we cannot do gets a visible "not implemented" label rather
  than a plausible-looking placeholder.