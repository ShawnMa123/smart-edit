# Design

## Context

See `proposal.md` — Why. The constraints that shape this design:

| Exists (verified) | Shape |
|---|---|
| `app/parsing/*` | pure functions, no `state` argument |
| `app/nodes/{parse,extract,normalize}.py` | `node(state, **opts) -> dict` returning **partial** updates |
| `app/stages.py` | `AGENT_SPECS`, `STAGE_TARGETS`, `stage_report()`, `latest_stage()`, `require()` |
| `app/standalone.py` | `plan_standalone(target, state) -> {"status", "error", "chain" \| "missing", …}` |
| `app/findings.py`, `app/trail.py`, `app/config.py` | numbering, trail write-back, `fields.yaml` loading |

| Missing | Consequence |
|---|---|
| `app/graph.py`, checkpointer | no reducer is applied anywhere in production code; that merge lives only in `tests/helpers.apply_update` |
| `app/api/` | no HTTP surface |
| LLM SDK / provider config | `extract_node` accepts an `llm` callable that nothing supplies |

Environment: repo-local `.venv` on CPython 3.12; `fastapi` / `uvicorn` declared in `pyproject.toml` but
not installed; no `web/` (the UI lives in `editor-shell`).

## Goals / Non-Goals

**Goals:**

- Three endpoints whose envelope is what `poc-skeleton` §9.7 promises, so swapping in the real graph
  later is invisible to clients.
- A single production implementation of "merge a node update into state", reused by tests.
- Honest failure modes: no provider ⇒ failed `extract` (never invented candidates); unknown run ⇒ 404
  (never an empty run); unbuildable `stages` ⇒ 500 (never a clean-looking 200).
- Zero new state keys, zero change to the frozen contract.

**Non-Goals:**

- Any `web/` code, `HITL` / `resume` / `events`, `gate` / `export` / `repair`, `agent2`–`agent4`.
- Persistence, authentication, multi-user, multi-run history.
- Implementing the graph (`poc-skeleton` §8) or reshaping `app/standalone.py`.

## Decisions

### D1. Drive the existing nodes behind a chain executor instead of building the graph

`app/runtime.py::execute_chain(state, chain, *, llm=None, fields_yaml=None)` loops over the stage names
returned by `plan_standalone()` and calls the nodes, merging each update.

*Why:* `app/graph.py` does not exist and belongs to another change; waiting would block every client,
while writing the graph here would duplicate work and pull `langgraph` checkpoint semantics into a
transport change. *Alternatives:* (a) install `langgraph` and build the graph here — crosses ownership;
(b) call nodes ad hoc from each endpoint — prerequisite ordering would be re-implemented per endpoint,
exactly the bug `plan_standalone()` prevents.

### D2. One production `merge_update()`, with the test helper re-exporting it

`merge_update(state, update)` appends for `findings` / `trail` / `stages` and overwrites everything
else; `tests/helpers.apply_update` becomes a thin re-export.

*Why:* reducer semantics currently exist only in test code, so production would either duplicate them
or overwrite `stages` — and every client's "did this run?" question depends on `stages` accumulating.
*Alternatives:* let the API append manually (two implementations, one untested); mutate `state` in
place inside the nodes (breaks the node contract that the graph will rely on).

### D3. Run store is in-memory and serialized per run

`app/runs.py` keeps `dict[thread_id, state]` plus one `asyncio.Lock` per run. `POST /runs` creates the
entry; a stage trigger holds the lock for the whole chain; reads return a copy of the envelope.

*Why:* no checkpointer exists and a POC needs no durability. The lock matters more than the store —
without it two concurrent triggers interleave appends into `trail` / `stages` and the run becomes
unreproducible. *Alternatives:* `langgraph-checkpoint-sqlite` (needs the graph); writing `runs.db`
ourselves (a second persistence format to keep in sync with the real one). No TTL: one process serves
one demo, and a restart is answered with `404 unknown_run`.

### D4. One envelope builder, and it refuses to fake completeness

`app/api/envelope.py::to_envelope(state)` is the only place a response body is assembled. When `stages`
cannot be produced it raises, and the handler turns that into `500 INCOMPLETE_RESULT`.

*Why:* the one bug a client cannot survive is being told "no problems" because a key was missing.
Concentrating assembly makes that a single reviewable function instead of N dict literals.
*Alternatives:* build the body per endpoint (drift, and nowhere to enforce the invariant).

### D5. Translate `plan_standalone()`'s vocabulary; do not rewrite it

`plan_standalone()` returns `{status, error}` with `error ∈ {unknown_stage, missing_prerequisite}`.
The API maps `unknown_stage → 409 unknown_stage`, `missing_prerequisite → 409 REFUSED` (carrying
`missing`), and checks `AGENT_SPECS[target].standalone is False` **before** the plan lookup so
`agent4 → 403 NOT_STANDALONE`.

*Why:* `app/standalone.py` belongs to `poc-skeleton`; reshaping its return value would create a second
owner for one contract. The order matters: `agent4` is not in `STAGE_TARGETS`, so without the registry
check first it would surface as `unknown_stage` and mislead the client. *Alternatives:* add `code` to
`plan_standalone()` — a cross-change edit for cosmetics.

### D6. Model provider is an injected adapter; absence fails the stage, never fakes it

`app/llm.py::resolve_llm()` reads `SMART_EDIT_LLM`:

| Value | Behaviour |
|---|---|
| unset | returns `None`; `extract` records `StageReport(failed, reason="no model provider configured …")` |
| `fixture:<path>` | replays a JSON fixture of candidates; the callable carries a `provider` attribute so the node can label the run |
| `openai:<model>` | raises `NotImplementedError` — reserved, never a silent fallback |

*Why:* the seam already exists (`extract_node(..., llm=…)`); what was missing is a policy for "no
provider". Inventing candidates would violate the project's first hard constraint, and requiring a key
would make the transport untestable today. *Alternatives:* add the `openai` SDK now (no key to use it);
auto-enable the fixture (indistinguishable from real extraction).

### D7. Pasted text is materialised as a real file, then parsed by the one parser

`POST /runs` with `text` writes it to `runs/<thread_id>/pasted.txt` (`text/plain`) and registers it as a
normal `SourceFile`.

*Why:* one parsing path means text and file runs cannot diverge, and `parse_file` already guarantees
`page` / `bbox` are `null` for `text/plain`. *Alternatives:* a separate `parse_text()` entry point (a
second parser to keep in sync).

### D8. What the build can run is served, not hardcoded

The envelope carries `supported_stages`, derived from `app/stages.py::STAGE_TARGETS`.

*Why:* the `document-editor` spec requires unimplemented stages to be labelled rather than implied
skipped, and a hardcoded list in a client would become a lie the day `agent2` lands. Serving it keeps
the claim derived from the registry that actually gates execution. *Alternatives:* clients hardcode the
pipeline (drift).

## Risks / Trade-offs

- **[Run state dies with the process]** → `404 unknown_run` with a message saying state is
  process-scoped; never an empty run. Upgrade path is D3 (real checkpointer).
- **[Two execution paths: chain executor now, graph later]** → one shared `merge_update()` (D2) and a
  test proving `execute_chain` yields the same state as merging node updates by hand.
- **[Re-triggering a completed stage degrades results]** → `extract` consumes `_candidates` and
  `normalize` clears them, so a second `normalize` would rebuild `fields` from nothing and turn every
  required field into a placeholder. Mitigation: the executor skips any stage whose latest report is
  `done`, mirroring how `plan_standalone()` computes backfill.
- **[Fixture runs mistaken for real extraction]** → provider label travels in the `extract` report
  `reason`, so no client can show a fixture result without the label available.
- **[Multipart uploads need a dependency]** → `python-multipart` is added explicitly rather than
  hand-rolling multipart parsing; it is the only new runtime dependency.
- **[Hidden coupling with the editor change]** → `editor-shell` consumes exactly these three endpoints;
  any change to the envelope shape must update `console-api` first, not the client.

## Migration Plan

Additive; no frozen file is rewritten (only `app/nodes/extract.py` gains a provider guard).

1. `~/.local/bin/uv pip install --python .venv/bin/python -e '.[dev]'` (brings `fastapi`, `uvicorn`,
   `python-multipart`, `httpx`).
2. `.venv/bin/uvicorn app.api.main:app --reload` → `curl` the three endpoints.
3. Rollback: delete `app/api/`, `app/runtime.py`, `app/runs.py`, `app/llm.py`; revert the two
   dependency lines and the `app/nodes/extract.py` guard. Nothing else references them.
4. When `poc-skeleton` §8 lands: replace `execute_chain`'s internals with a graph invoke and drop the
   per-run lock; endpoints, envelope and error codes stay valid.

## Open Questions

1. **Artifact language.** This change's artifacts are English per an explicit instruction while
   `openspec/config.yaml` still declares `Language: zh`. Flipping that line affects all three owners,
   so it stays a team decision; the CLI's `context` remains as configured meanwhile.
2. **Which fixture file demos extraction.** `SMART_EDIT_LLM=fixture:<path>` needs one agreed fixture;
   `agent-normalize` owns that directory, so the path is chosen there. Deferrable — no spec or task
   shape depends on which file.
3. **Real provider adapter.** `SMART_EDIT_LLM=openai:<model>` stays reserved until an SDK and a key
   exist; adding it touches `app/llm.py` only.