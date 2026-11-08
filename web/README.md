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

### Importing a file

`Import file` (header) uploads a PDF / DOCX / PNG / JPEG and fills the editor with the text the server
read out of it: `POST /api/runs` (multipart) → `POST /api/runs/{id}/stages/parse` → read
`documents[]` from the envelope. Images and scanned PDFs need a local OCR engine
(`brew install tesseract tesseract-lang`); text-layer PDFs and DOCX do not.

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
| `desktop` | `:8000` with `SMART_EDIT_LLM=fixture:…` | `:5173` | 1440×900 | happy path, stale report, refusals, unimplemented tabs, three-pane layout |
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

Rich-text formatting, file import/OCR, server-side versions/locks/approvals, structural diff, the
knowledge/automation/legal assistant tabs, semantic checks, template rule packs and regulatory
coverage. Each is labelled "not implemented in this build" in the UI rather than simulated — see
`openspec/changes/editor-shell/design.md` Non-Goals and the `Requirements.md` §14 gap table.