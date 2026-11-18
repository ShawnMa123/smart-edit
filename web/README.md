# smart-edit web — three-pane document workspace

Planning artifacts: `openspec/changes/editor-shell/` (`proposal.md`, `specs/document-editor/spec.md`,
`design.md`, `tasks.md`).

## Ports and proxy (task 1.2)

| Side | Address | Notes |
|---|---|---|
| API (uvicorn) | `http://127.0.0.1:8000` | `app/api/main.py` — routes are `/runs*` with **no** `/api` prefix |
| Web (vite dev) | `http://localhost:5173` | Proxies `/api/*` → `http://127.0.0.1:8000`, stripping the `/api` prefix (`vite.config.ts`) |

The client keeps the `/api` prefix (`VITE_API_BASE`, default `/api`) so the SPA's own routes and the
API namespace never collide. Anything that must hit the API without a proxy can set
`VITE_API_BASE=http://127.0.0.1:8000`.

## Run it

```bash
# terminal A — backend, fixture-backed so the audit has candidates to work with
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json .venv/bin/uvicorn app.api.main:app --reload

# terminal B — frontend
npm --prefix web install
npm --prefix web run dev        # http://localhost:5173
```

### Shell layers

Above the three-pane grid the workspace renders three layers (`web/src/components/AppShell.tsx`):

| Layer | Content | Rule |
|---|---|---|
| Top bar (`.topbar`) | product mark, `PRODUCT_NAME` (configurable), `Local demo session` | shows **no** person, avatar, organisation or member entry |
| Environment strip (`.environment-strip`) | synthetic data, fixed snapshot, assistant does not approve, history/templates in this browser | one standing summary; panels keep their own specific statements |
| Document header (`.document-head`) | breadcrumb `{document section} / {documentId}`, stored title, `Draft` tag, meta line | meta lists only facts the client holds; digest, lock and storage sit behind `Technical details` |

The build has no authentication, so the shell must never look like a signed-in session. Copy that
lacks a data source is omitted rather than filled with a sample value — for example, the header does
not show counterparties, a template number or participating organisations, and the breadcrumb uses
`draft.document_id`.

### Workspace modules

A 58px desktop rail exposes Document, Versions, Approval, Comments, People and Developer. The top
bar exposes Activity, People, Inbox, Developer and the neutral `Local demo session` entry. The rail
disappears below the three-pane breakpoint; the same entries remain reachable through the pane
switcher's `More` menu.

| Entry | Behavior |
|---|---|
| Document / Versions | switch the existing content panes; no new backend |
| Activity | browser-local activity list from `smart-edit:activity:<documentId>`; clear requires confirmation |
| Inbox | derived from `notifiable` activity; unread count; Mark all read stays local |
| Developer | read-only implementation map (Available / Partial / Unavailable) |
| Version compare | select exactly two captured versions; read-only block diff |
| People / Identity / Approval / Comments | explicit placeholders that name the missing backend capability and render no sample members, organisations, approvers or comments |

The placeholder dialogs make no network request and write no data. `People` and `Identity` must keep
the shell's no-unauthenticated-identity rule; do not add sample names, avatars or organisations.

The document header exposes `Import file` (real file chooser), `Comments` (explicit placeholder for
the missing comment service), and `Export` / `Start approval` with a `Not available` tag. Formatting
is available through the editor toolbar and keyboard shortcuts; the header must not show a stale
`Formatting · Not available` action.

The editor footer exposes `Release lock`, `Start editing` and `Submit new version`. The lock controls
call the real document lock APIs; `Submit new version` is a visual placeholder that states shared
submission is not available, and offers a real `Capture browser-local version` action instead. It
never claims the document was sent, submitted or approved.

### Demo data mode

`Demo data` is an explicit, default-off switch in the environment strip. It is stored under
`smart-edit:demo-mode`; when on, the first-batch collaboration surfaces use a separate browser-local
store at `smart-edit:demo:collaboration:v1`. The banner states that sample users, organisations and
approvals are demo data, **not real authentication or a real workflow**.

Demo state is isolated from the real activity/version/draft stores. `Reset demo data` restores the
seeded sample state only; it does not touch real activity, version history or the server draft.
Turning the switch off restores the honest mode: neutral `Local demo session`, unavailable
People/Approval/Comments placeholders and the real activity log.

### Activity and notifications

The `Activity` and `Inbox` entries are backed by a browser-local log, not a server audit trail.
Entries live under `smart-edit:activity:<documentId>` in `localStorage`, are capped at 100, and
only describe real operations the operator performed in this workspace (import, save, version
capture/restore, audit, knowledge answer, template apply, export attempt). The log never stores the
question, document text, citation text, identities or credentials. Clearing the log only removes
this browser key; it does not touch version history, the draft or any audit result.

Notifications are a derived view of `notifiable` activity entries; opening Inbox marks the local
entries read and never sends a read receipt to the backend. When storage is unavailable or corrupt,
the UI says the log is session-only instead of claiming it was saved.

| Kind | Recorded when | Notifiable |
|---|---|---|
| `import` | a file import succeeds or fails | yes |
| `save` | a user-edited draft is saved | no |
| `conflict` | the server rejects a save with a conflict | yes |
| `capture` | a version is captured | yes |
| `restore` | a captured version is loaded as a draft | no |
| `audit` | an audit starts, completes or fails | start no; result yes |
| `knowledge` | a knowledge answer completes or fails | yes |
| `template` | a template is applied to the editor | yes |
| `export-attempt` | the unavailable Export action is activated | no |

The activity record never stores the question, document text, citation text, identities or
credentials; it only stores the action label, a short result detail, the timestamp and the local
read/notification flags.

### Version comparison

`Version compare` selects exactly two browser-local captured versions and renders a read-only block
diff of their projected text. The dialog shows both labels, capture times and short digests; it
never creates a version, rewrites history, changes the current draft or asks an AI model for a
summary. Adjacent removed/added blocks are shown as `changed`. With fewer than two captured
versions the Compare action explains that two are required.

### Interface language

The interface is **English only** (`interface-language`):

- `web/index.html` declares `lang="en"`, and the document `<title>` is English.
- Chrome copy — shell, panes, assistant tabs, status band, empty states, notices — is English. The
  header title comes from `draft.title` (fallback `Untitled document`) and the breadcrumb from
  `draft.document_id`; no translation gloss and no example reference such as `DG-2026-00417`.
- `App.tsx` pins the knowledge binding to `locale="en"`, so assistant sessions request `en` and only
  the English corpus (`fixtures/knowledge/*_en.json`) supplies citations.
- Document **content** may be any language. `e2e/interface-language.spec.ts` scans the named chrome
  roots only — never the editor body or citation excerpts — and fails if Chinese characters appear there.

### Editing the document

The centre pane is a **rich-text editor** (TipTap/ProseMirror), not a textarea: headings, bold/italic/
underline, lists and tables are real, and imported structure is preserved. The audit still reads a plain
text projection, so formatting cannot change a verdict:

| Editor | Projected into the audit text |
|---|---|
| heading 1–3 | `#` / `##` / `###` + text |
| paragraph | text (bold/italic/underline are dropped) |
| bullet / numbered list | `- item` / `1. item` |
| table | one line per row, cells joined with ` | ` |

The projection lives in `src/rich/projection.ts` (re-exported as `richToPlainText`) and is covered by
golden tests; formatting-only edits therefore leave the snapshot digest and the audit result unchanged.
Selection offsets are Unicode code points, not UTF-16 units. If the editor cannot start at all,
`RichEditor` falls back to a textarea and says why — a blank pane is never the failure mode.

The document is rendered as a **page** (`.paper-wrap > article.paper`): a centred sheet with a page
header (`DOCUMENT WORKING COPY` plus the stored document id), a serif body and a page footer with the
captured version count. The page is a container only — `richToPlainText` receives exactly the same
document, so the projection, character count and digest are unchanged by the presentation.

Above the toolbar, `.editor-status` is the single status band. It shows the snapshot (`snapshot vN` or
`no captured version`), the server draft (`draft rev N` or `no server draft`), the edit lock
(`lock: this session` / `lock: unknown`) and the `data-testid="save-state"` message. The band and the
conflict panel read the same `saveState` value, so they cannot disagree.

### Server draft, autosave and conflicts

The centre pane now has a server-authoritative draft (`/api/documents/*`, local/test only). On first
load it reads the draft, acquires an edit lock and autosaves 2 seconds after typing with
`If-Match: "draft-<revision>"`. The status band says `Saving…`, `Saved to server`, `Save failed` or
`Save conflict`; it never reports `Saved` before the host accepted the write.

A `412 stale_draft` **does not replace the editor**. The local content stays, a recovery draft is
written to `localStorage` (`smart-edit:recovery:demo-document`), and the conflict panel offers
`Use server version`, `Overwrite with local content` or `Keep local as recovery draft`. The host
still rejects automation apply/undo when the draft head moved; they never auto-rebase (the run core is
covered by API tests, not by the Automation tab UI).

Variables are versioned separately from content: `PUT draft` no longer carries variables, and a
text-only save preserves the existing variables and `variables_version`. Variable updates use
`PATCH /documents/{id}/drafts/{draft_id}/variables` with `If-Match: "variables-<version>"`.

### Automation tab (fixture-backed workbench)

The assistant's **Automation · fixture only** tab is a frontend-first workbench with three areas:

- **Template** captures the current imported or edited document as a template snapshot. Before saving,
  a live preview shows the source (`Imported · deterministic/heuristic/fallback` with its note, or
  `Edited in this browser`), the draft revision (or `No server draft`), character count, variable
  summary and the next version; a duplicate name warns that a new version is added instead of
  overwriting. Captured templates appear as cards with a detail view (source, captured time,
  character count, variables, 240-character content excerpt), inline rename with validation, and a
  Two-step delete. Templates are snapshots: later edits to the working document never change them.
  `Apply to editor` replaces the current document with a template (confirmation when it has content;
  empty documents apply directly), keeping captured variable values and provenance, then uses the
  normal autosave path. `Save to template` in Variables & Fill updates an existing template in place
  (same id/name, version+1, previous snapshot replaced; no history in this build).
  Storage is browser-local (`localStorage`, `smart-edit:automation-templates`, at most 20, oldest
  evicted), so the UI says `Saved in this browser — not on the server`; quota/corrupt/unavailable
  storage degrades to a readable message and, for failed writes, a visibly session-only record.
- **Variables & Fill** marks a non-empty paragraph/heading selection as a `variableReference` node
  (right-click, the toolbar button or `Alt+Shift+V`), lists every occurrence and previews the
  before/after value for each one. Filling updates only nodes with the same `variableId` and never
  same-named ordinary text; deleting a required variable reports it as missing.
- **Downstream Mapping** has two sources. `Synthetic fixture` matches a synthetic downstream API
  template deterministically (for example `application_type = guarantee` with an evidence excerpt),
  requires an explicit per-field `Confirm`, and renders a JSON payload preview bound to the mock
  template version and the document digest. `OpenAPI JSON` accepts an uploaded or pasted OpenAPI 3.x
  JSON document (parsed locally, never uploaded or saved), resolves local `$ref`, lists operations
  with an `application/json` request body, flattens object properties into dotted paths, suggests
  variable mappings by label with manual override, and blocks readiness on missing required fields,
  enum mismatches and number/integer/boolean conversion failures. Synthetic date fields are normalised
  to `YYYY-MM-DD` before entering the payload: ISO, `YYYY/MM/DD`, `DD/MM/YYYY`, `DD/MM/YY`,
  `YYYY年MM月DD日` and English month names are accepted; `12/03/27` becomes `2027-03-12` (DD/MM is the
  default, MM/DD only when the second segment is >12), and invalid calendar dates stay missing. Downstream systems are managed in a
  collapsible `Manage systems` surface (name, base URL, environment, enabled, non-secret auth
  type/hint, bound spec) and stored in browser-local `localStorage`, seeded once from mock presets
  (max 10 systems, spec ≤ 512 KB). Ready payloads can be downloaded as `.json`; `Send (mock)` returns
  a deterministic 200 `mock_success` or, with `Simulate failure`, a 500 `MOCK_DOWNSTREAM_ERROR`.
  Receipts always say `Simulated — no network request`; no real send/execute, fetch, credential read
  or send history exists. YAML, Swagger 2.0, URL fetching, external `$ref`, `oneOf` and `anyOf` are
  explicitly unsupported.

Synthetic variable fill and fixture mapping are mock-backed (`web/src/automation/mockWorkbench.ts` +
`fixtures/automation/workbench_demo.json`); template snapshots use the browser-local
`web/src/automation/templateStore.ts`; downstream systems use
`web/src/automation/downstreamSystemStore.ts` and `fixtures/automation/downstream_systems.json`;
OpenAPI JSON is parsed locally by `web/src/automation/openapi.ts`, exported by `payloadExport.ts`,
and mock-sent by `mockDownstreamSend.ts` without any network request. There is no server template or
system registry (and no stored credentials), no extract/confirm model, no real API template import
and no real delivery. Synthetic previews say `Not sent`; mock receipts say
`Simulated — no network request`. The previous `rewrite/replace_text` fixture run panel no longer owns
the tab; the run/result/apply/undo contract stays covered by API tests and
`tests/test_automation_apply.py`. When the editor falls back to a textarea, `{{label}}` placeholders
are shown and variable actions are disabled.

`Import file` (header) uploads a PDF / DOCX / PNG / JPEG and fills the editor with the text the server
read out of it: `POST /api/runs` (multipart) → `POST /api/runs/{id}/stages/parse` → read
`documents[]` from the envelope. Images and scanned PDFs need a local OCR engine
(`brew install tesseract tesseract-lang`); text-layer PDFs and DOCX do not.

### Assistant tabs

The assistant keeps the reference tab set on one row. Each tab shows a short visible label plus a
separate capability tag, while its accessible name carries both: `Rule audit`, `Knowledge Q&A`,
`Automation · fixture only`, `Legal advice · not implemented`. The pattern is `tabLabel()` in
`AssistantPanel.tsx`; the visible label must stay short enough for four tabs at the 352px pane width,
and a non-`Full` tag must be accompanied by a limitation statement inside the panel.

### Web search, local RAG and outbound screening

The assistant can combine three evidence layers, and every external call is gated **before** it is
made. Nothing is enabled by default: with no configuration the assistant still answers from the
published corpus and the bound snapshot and makes no outbound request.

| Setting | Env | Default | Effect |
|---|---|---|---|
| Model provider | `SMART_EDIT_ASSISTANT_MODEL=doubao:<model>` + `SMART_EDIT_ASSISTANT_API_KEY` | empty (fixture composer) | Ark **Responses API** (`POST /responses`, `stream:false`, no tools); output must validate against the Answer schema |
| Approved processor | `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED=1` | off | only an approved processor may receive the question + evidence bundle; anything else is refused |
| General web channel | `SMART_EDIT_ASSISTANT_GENERAL_WEB=1` | off | answers **out-of-scope, non-handoff** questions with exactly one read-only `web_search` tool; results are `general_web`, capped at `qualified` |
| Web search keywords | `SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD` | 3 (1–5) | `max_keyword` sent to the provider's search tool |
| Hidden reasoning | `SMART_EDIT_ASSISTANT_THINKING` | off | Ark `thinking` is disabled for latency; set `1` to let the model reason (10–60s per call) |
| Web layer | `SMART_EDIT_ASSISTANT_WEB=off\|fixture\|http` (+ `…_WEB_ENDPOINT`) | off | per-run opt-in; only allow-listed domains survive |
| Local RAG | `SMART_EDIT_ASSISTANT_RAG_ENDPOINT` (+ `…_RAG_API_KEY`) | empty (lexical corpus) | second layer; failures degrade visibly |
| Egress policy | `SMART_EDIT_ASSISTANT_EGRESS_POLICY` | `app/configs/egress.yaml` | missing/broken file denies every web request |

Rules the implementation keeps:

- **Opt-in per run**: `POST /assistant/sessions/{id}/runs` accepts `web_search: true`; the panel
  checkbox defaults to off and describes exactly what will and will not leave the service.
- **Search traffic never carries document content**: selection text, amounts, references,
  counterparties and identity are denied or redacted (`EgressPolicy`), and every decision is audited
  (`egress_allowed` / `egress_blocked{reason}`).
- **Approved processors are the only exception**: an external model may receive the question and the
  evidence bundle only when it is registered as an approved processor; otherwise the run fails with
  `EGRESS_BLOCKED` instead of silently falling back to the fixture composer.
- **Web evidence is bounded**: `approved_web` citations carry `{url, domain, retrieved_at, provider,
  rank}`, web-only claims cap `support_level` at `qualified`, rule version/applicability cannot come
  from the web, and conflicts are kept rather than auto-resolved.
- **Failures are stated**: a blocked or failed web layer adds a limitation and the UI shows
  `Web search blocked (<reason>)` or `Web search did not complete`; it never implies live verification.
- **Fallback to general web**: when an in-scope question ends with `insufficient_evidence` and no
  published citation, and the operator enabled web search, the assistant falls back to the general
  channel. The answer is marked `general_web`, carries both "published corpus could not answer" and
  "unverified third-party content", and is capped at `qualified`.
- **Two separate model calls**: composing never carries tools; only the general channel attaches
  `tools: [{type: "web_search", max_keyword: N}]` and only for out-of-scope, non-handoff questions.
  General citations are grouped under `General web (n)` and always shown with an unverified banner.

Tests: `tests/test_egress_policy.py`, `tests/test_assistant_retrieval_layers.py`,
`tests/test_assistant_gateway.py`, `tests/test_assistant_settings.py`, plus the panel cases in
`web/src/components/KnowledgePanel.test.tsx`.

#### Why didn't it search?

`GET /assistant/capabilities` answers that without guessing:

| Field | Meaning |
|---|---|
| `model.configured` / `model.label` | a real provider is wired; `false` means the answer is `processor: fixture` |
| `model.approved_processor` | outbound content may be sent to that provider (`PROCESSOR_APPROVED`) |
| `layers.approved_web` | the allow-listed web provider is wired (`WEB=fixture\|http`) |
| `layers.general_web` | the provider's read-only `web_search` tool may run (`GENERAL_WEB=1` + approved processor) |
| `egress.loaded` / `allowed_domains` | the outbound policy is usable and how many domains it allows |
| `web.provider` | `off`, `fixture` or `http` |

The panel disables the toggle when both web layers are `false`, and every answer carries
`route` (`published \| document \| general_web \| handoff \| none`) plus a `web` summary
(`requested / status / reason / hint`) so “skipped because the server has no provider” is stated in
the answer instead of being inferred from logs.

### Knowledge Q&A (right pane)

The `Knowledge Q&A` tab is wired to `/api/assistant/*`; `Legal advice` remains labelled
`not implemented`, while `Automation` is an available fixture-backed workbench. The panel registers an immutable snapshot + session on the first question, sends
`POST /api/assistant/sessions/{id}/runs` (202), polls `GET /api/assistant/runs/{id}`, and renders the
reviewed answer: outcome, support level, claims, citations, limitations, clarification questions or the
handoff target. Citation cards read `GET /api/assistant/messages/{id}/citations/{cid}` (allowed excerpt +
locator only); feedback is `PUT …/feedback` and replaces the previous rating.

Honesty rules the UI keeps: a `Fixture-backed` banner is always visible (the corpus is synthetic, not
legal text), no placeholder answers or citations are rendered, a technical failure is not shown as
`insufficient_evidence`, and an older bound snapshot is called out with a "start a new conversation"
action. `web/src/api/assistant.ts` is the only module that talks to the assistant API; the contract types
live in `web/src/api/assistantTypes.ts` and mirror the server DTOs.

The demo corpus is **8 synthetic sources / 72 chunks** (Chinese 36 + English 36: 12 product manual, 12 trade-rule summaries, 8 internal-policy chunks, 4 help-guide chunks per language), all `synthetic: true`. The reproducible evaluation set is **33 questions** and is run with `python scripts/assistant_eval.py`; it measures citation hit, outcome accuracy and clarification accuracy only (no embeddings, reranking or model).

On first open the knowledge tab shows an English **Can / Cannot / How** card and up to 3 English suggested
questions (`What can you do?`, `What documents are required for the application?`,
`What does URDG 758 article 20 require for claims?`; the selection variant uses
`What does this passage mean?`). Clicking a suggestion only fills the question and focuses the input; it
never creates a run. After the first answer the suggestions collapse into `Show examples`. English
questions retrieve only English sources, Chinese questions only Chinese sources, and capability questions
are answered from the matching published help guide with a citation.

Failures are listed per file and are never dressed as success — a file with errors gets no "use this
text" action. The user-facing wording for each code lives in `src/components/ImportReport.tsx`:

| Code | What the screen says |
|---|---|
| `unsupported_mime` | "This file type is not supported (PDF, DOCX, PNG and JPEG are)." |
| `ocr_engine_missing` | "The local OCR engine is not installed on the server, so images cannot be read right now." |
| `no_text_recognized` | "No text could be recognised in this file." |
| `image_open_failed` / `pdf_open_failed` / `docx_unreadable` | "This image/PDF/DOCX could not be opened/read." |
| `file_too_large` / `too_many_pages` | "…larger than the import limit" / "…more pages than the OCR limit allows" |

Text recognised by OCR is labelled `Image · recognised text, please check`; the fields extracted from it
stay `inferred` and cannot pass a rule check until a human confirms them.

`Run spec audit` inside the app issues **three** calls: `POST /api/runs`,
`POST /api/runs/{id}/stages/normalize`, and then — only when `extract` **and** `normalize` finished —
`POST /api/runs/{id}/stages/audit`. The right pane renders the field table (normalization) and the rule
audit block (`verification.checks`, `verification.audit`, `gate`) from that last envelope.

Template-driven audit is **opt-in**: append `?template=<template_id>` to the audit call and the envelope
gains `verification.audit.template` (id / version / `content_sha256` / `synthetic` / `resolved_from` /
`policy_packs` / `conflicts`). Without it the audit runs on the base schema and the published rule packs,
and the baseline says `template_not_requested` — never "no template, therefore clean". The panel shows
the template block once the frontend is wired to the query parameter; today `how_to_use.md` §5 exercises
it with `curl` and `scripts/audit_demo.py`.

The full click-by-click walkthrough, with the numbers to expect, lives in `../how_to_use.md`.

Run the backend **without** `SMART_EDIT_LLM` to see the honesty path: `extract` fails, the panel says the
field checks did not run **and** the rule audit did not run, instead of blaming the document. The audit is
never attempted on placeholder fields.

## Checks

```bash
.venv/bin/python -m pytest -q                 # Python, incl. document host + automation apply/undo
.venv/bin/python scripts/automation_demo.py   # fixture proposal -> accept -> apply -> undo (in-memory)
npm --prefix web run typecheck  # tsc --noEmit
npm --prefix web run test       # vitest (jsdom); the HTTP e2e is skipped without VITE_E2E=1
npm --prefix web run build      # emits web/dist/index.html

# real HTTP end-to-end against a running backend
VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.audit.test.ts
```

## UI end-to-end (Playwright)

`e2e/` drives a real browser against a real backend:

```bash
npm --prefix web run e2e                       # all projects
npm --prefix web run e2e:headed                # watch the desktop project run
npm --prefix web run e2e:report                # open the HTML report after a CI run
npm --prefix web e2e -- --project=honesty      # only the no-provider path
```

`playwright.config.ts` starts four servers itself, so no manual setup is needed — but **kill leftovers
first**, they are the number one cause of fake failures:

```bash
for p in 8000 8010 5173 5174; do lsof -nP -iTCP:$p -sTCP:LISTEN -t | xargs -r kill -9; done
```

| Project | Backend | Frontend | Viewport | Covers |
|---|---|---|---|---|
| `desktop` | `:8000` with `SMART_EDIT_LLM=fixture:…` | `:5173` | 1440×900 | happy path, stale report, refusals, knowledge Q&A, fixture-backed automation workbench, unimplemented legal tab, three-pane layout |
| `honesty` | `:8010` with `SMART_EDIT_LLM=''` | `:5174` (`VITE_PROXY_TARGET`) | 1440×900 | "checks did not run", and **no** `/stages/audit` request |
| `narrow` | `:8000` | `:5173` | iPhone 13 | one pane + tabs below 1366px, audit still reachable |

Two things worth knowing:

- The desktop project must be **≥1366px** — Playwright's default 1280×720 is the narrow layout in this
  app (`useViewport.ts`).
- The second vite instance exists because `app/api/main.py` has **no CORS middleware**; the browser can
  only reach `:8010` through a dev proxy, hence `VITE_PROXY_TARGET` in `vite.config.ts`.

Assertions stay on the data, not the pixels: `data-testid` hooks in `AuditPanel` / `EditorColumn`, stage
rows carrying `data-stage`/`data-status`, gate carrying `data-decision`. Nothing snapshots the page —
copy changes weekly, and a test that breaks on wording teaches the team to delete tests.

All three checks in one command (what CI runs):

```bash
npm --prefix web run verify   # typecheck → vitest → playwright
```

Browser resolution — **nothing is ever downloaded** if you set one of these (needed on a restricted
intranet):

| Env | Uses |
|---|---|
| `PW_CHANNEL=chrome` | the installed Google Chrome (CI default) |
| `PW_EXECUTABLE_PATH=/path/to/chrome` | a pinned Chrome/Chromium binary baked into the image |
| `PW_VIDEO=1` | additionally records video (requires `npx playwright install ffmpeg`) |

Without either variable Playwright looks for its own bundled build, which needs a one-off
`npx playwright install chromium` (~200 MB) — skip that on a locked-down network.
|---|---|---|
| Audit panel says `HTTP_500 … backend is not running` | The dev proxy answered because nothing listens on `:8000` | Start uvicorn (see above). The vite log prints `http proxy error … ECONNREFUSED 127.0.0.1:8000` |
| Audit panel says `Field checks did not run` | Backend started without `SMART_EDIT_LLM` — `extract` failed by design | Restart the backend with the fixture provider, or accept the honest path |
| Browser shows `ERR_CONNECTION_REFUSED` on `:5173` | `npm --prefix web run dev` is not running (it blocks its own terminal) | Run it in a **second** terminal; check for the `Local: http://localhost:5173/` line |
| Panel says the report is stale right after a run | The editor text changed after the audit started (including a trailing newline) | Re-audit the current snapshot; the digest shown is the one that was audited |
| `409 unknown_stage: unregistered stage target: audit` | A backend started **before** the audit stage existed is still holding the port | Kill it (`lsof -nP -iTCP:8000 -sTCP:LISTEN -t \| xargs kill -9`) and start uvicorn again |
| Rule audit block says `Not asked` | Correct: nothing asked the gate about an operation | Expect this until a gate endpoint exists; use `scripts/audit_demo.py` to see decisions |

## What this build deliberately does not do

The document host is a **local/test** adapter only: one process, one writer, fake identity, no
PostgreSQL/Worker/multi-tenant host, and no production deployment. There is still no structural diff,
real semantic automation model, regulatory coverage, approved production identity/snapshot/model
adapters, real models/embeddings/reranking, controlled web access, voice/screenshot or export.
Automation is available only as a fixture-backed frontend workbench (template capture, variable fill
and downstream mapping/payload preview) and is labelled `fixture only`; the real run core still exists
behind the API but no longer owns the tab. Legal remains labelled "not implemented in this build". The
workbench demonstrates the interaction structure, not a general semantic automation assistant.
The knowledge tab is explicitly `Fixture-backed` — see `openspec/changes/document-host-foundation/`,
`openspec/changes/agent-knowledge/` and the `Requirements.md` §14 gap table.