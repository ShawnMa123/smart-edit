# Proposal

## Why

`agent-normalize` works only in-process: `parse_node` / `extract_node` / `normalize_node` take a state
dict and return an update. There is no HTTP surface, so no screen, script or future `HITL` review can
use it — and `poc-skeleton` §9 only *describes* the endpoints, it never implements them.

This change builds that transport, and nothing else. Every consumer benefits: the editor planned in
`editor-shell`, a `curl` during a demo, and whatever `poc-skeleton` §8 eventually wires the graph into.
It also fixes three failure modes that only appear once the pipeline is reachable over HTTP: reducer
keys silently overwritten, a demo that invents candidates when no model provider is configured, and a
vanished run that looks like a clean run.

## What Changes

- **New `app/runtime.py`**: `merge_update()` (the single production implementation of the reducer
  semantics for `findings` / `trail` / `stages`) and `execute_chain()` (runs a stage chain from
  `plan_standalone()` through the existing nodes).
- **New `app/llm.py`**: model-provider resolution from `SMART_EDIT_LLM` (`fixture:<path>` supported,
  `openai:<model>` reserved, unset = none). Absence fails the `extract` stage loudly; a fixture-backed
  run is labelled in the stage report.
- **New `app/runs.py`**: process-scoped run store keyed by `thread_id`, with one lock per run so two
  concurrent stage triggers cannot interleave reducer appends.
- **New `app/api/`** (FastAPI): `POST /runs` (files or text), `POST /runs/{thread_id}/stages/{stage}`,
  `GET /runs/{thread_id}`; one envelope builder that refuses to omit `stages`; one error body shape
  `{code, message, detail?}` covering `EMPTY_SUBMISSION` / `unknown_run` / `unknown_stage` /
  `REFUSED` / `NOT_STANDALONE` / `INCOMPLETE_RESULT`.
- **New dev dependency `httpx`** (TestClient) and **`python-multipart`** (multipart uploads).
- **Supersedes the UI this change originally planned.** The single-screen console is replaced by
  `editor-shell`'s three-pane workspace; its `frontend-console` capability is removed from this change,
  so archiving here will not create a UI capability nobody builds.

**Not in this change**: any `web/` code, `HITL` / `resume`, `GET /runs/{tid}/events`, `gate` / `export`
/ `repair`, `agent2` / `agent3` / `agent4`, persistence, authentication.

**BREAKING**: none — no existing behaviour is removed.

## Capabilities

### New Capabilities

- `console-api`: the HTTP boundary for one run — creation, stage triggering, result reads, the
  machine-readable error `code` table, run-state lifetime, and the failure mode when no model provider
  is configured.

### Modified Capabilities

None. `openspec/specs/` holds no archived capability yet, and no existing requirement changes: the
stage-triggering and observability requirements this implements live in
`poc-skeleton/specs/orchestration/spec.md`, which this change satisfies rather than restates.

## Impact

- New files: `app/runtime.py`, `app/llm.py`, `app/runs.py`, `app/api/{__init__,main,envelope,errors}.py`,
  `fixtures/llm/extract_sample.json`, `tests/test_{runtime,llm,runs,api,contract_parity...}.py`
- Small edits to `app/nodes/extract.py` (refuse when no provider is supplied; surface a fixture
  provider in the stage `reason`) and `app/stages.py` usage stays untouched
- `pyproject.toml`: dependencies gain `python-multipart`; the `dev` extra gains `httpx`
- `.gitignore`: `runs/`
- Consumers: `editor-shell` (its `document-editor` spec), `curl`, and later the `HITL` screen
- Reads only the frozen `app/state.py`; no state key is added
- Risk: a process-scoped store means a restart loses runs — answered with `404 unknown_run`, never an
  empty result (see `design.md` D3)