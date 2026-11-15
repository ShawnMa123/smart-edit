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

### Server draft, autosave and conflicts

The centre pane now has a server-authoritative draft (`/api/documents/*`, local/test only). On first
load it reads the draft, acquires an edit lock and autosaves 2 seconds after typing with
`If-Match: "draft-<revision>"`. The footer says `Saving…`, `Saved to server`, `Save failed` or
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
  enum mismatches and number/integer/boolean conversion failures. Ready payloads can be downloaded
  as `.json`; the UI always says `Not sent` and exposes no send/execute action. YAML, Swagger 2.0,
  URL fetching, external `$ref`, `oneOf` and `anyOf` are explicitly unsupported.

Synthetic variable fill and fixture mapping are mock-backed (`web/src/automation/mockWorkbench.ts` +
`fixtures/automation/workbench_demo.json`); template snapshots use the browser-local
`web/src/automation/templateStore.ts`; OpenAPI JSON is parsed locally by
`web/src/automation/openapi.ts` and exported by `payloadExport.ts`. There is no server template
registry, no extract/confirm model, no real API template import and no delivery. Both mapping
previews say `Not sent` and there is no send/execute button. The previous `rewrite/replace_text`
fixture run panel no longer owns the tab; the run/result/apply/undo contract stays covered by API
tests and `tests/test_automation_apply.py`. When the editor falls back to a textarea, `{{label}}`
placeholders are shown and variable actions are disabled.

`Import file` (header) uploads a PDF / DOCX / PNG / JPEG and fills the editor with the text the server
read out of it: `POST /api/runs` (multipart) → `POST /api/runs/{id}/stages/parse` → read
`documents[]` from the envelope. Images and scanned PDFs need a local OCR engine
(`brew install tesseract tesseract-lang`); text-layer PDFs and DOCX do not.

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