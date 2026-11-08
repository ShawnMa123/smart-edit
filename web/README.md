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

`Run spec audit` inside the app issues **three** calls: `POST /api/runs`,
`POST /api/runs/{id}/stages/normalize`, and then — only when `extract` **and** `normalize` finished —
`POST /api/runs/{id}/stages/audit`. The right pane renders the field table (normalization) and the rule
audit block (`verification.checks`, `verification.audit`, `gate`) from that last envelope.

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

## Troubleshooting

| Symptom | Cause | Fix |
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