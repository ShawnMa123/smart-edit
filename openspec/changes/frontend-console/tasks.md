# Tasks

> API-only after trimming: the console UI moved to `editor-shell`. This change must not touch
> `app/state.py`, `app/stages.py` contracts, `app/standalone.py`, or add any `web/` file.

## 1. Runtime seams

- [x] 1.1 `app/runtime.py::merge_update(state, update)` — append for `findings` / `trail` / `stages`,
  overwrite otherwise. Verify: `tests/test_runtime.py` asserts a second merge appends (not replaces)
  and that `_candidates` is overwritten.
- [x] 1.2 `tests/helpers.apply_update` re-exports `merge_update` so only one implementation exists.
  Verify: the existing 78 tests still pass and `grep -rn "def apply_update" app tests` returns nothing.
- [x] 1.3 `app/runtime.py::execute_chain(state, chain, *, llm=None, fields_yaml=None)` runs the named
  stages in order through the existing nodes. Verify: test asserting the result equals merging the node
  updates by hand for `["parse", "extract", "normalize"]`.
- [x] 1.4 A stage whose latest report is `done` is skipped, not re-executed. Verify: test that running
  `normalize` twice leaves `fields` intact (no flood of `missing` placeholders) and adds no new stage
  report for the target.
- [x] 1.5 An unregistered stage name raises before any node runs. Verify: test asserting the exception
  and that the input state is unchanged.

## 2. Model provider adapter

- [x] 2.1 `app/llm.py::resolve_llm()` returns `None` when `SMART_EDIT_LLM` is unset. Verify: test with
  the variable cleared via monkeypatch.
- [x] 2.2 `SMART_EDIT_LLM=fixture:<path>` returns a callable that replays the file's candidates and
  carries a `provider` attribute naming the fixture. Verify: test asserting the returned candidates carry
  `key` / `raw_value` / `span` / `confidence` and that `provider` mentions the path.
- [x] 2.3 `SMART_EDIT_LLM=openai:<model>` raises `NotImplementedError` with a message naming the missing
  adapter. Verify: test asserting the raise and that no fallback callable is returned.
- [x] 2.4 `app/nodes/extract.py` refuses when `llm is None`: one `StageReport(stage="extract",
  status="failed")` whose `reason` names the missing provider, no candidates written. Verify: test
  asserting the failed report and that `_candidates` stays empty.
- [x] 2.5 A fixture-backed run is labelled: when the provider attribute is set, the `extract` report
  `reason` states the candidates came from that fixture. Verify: test asserting the reason text differs
  between a fixture run and a provider run.
- [x] 2.6 Commit `fixtures/llm/extract_sample.json` satisfying `schemas/candidates.json`. Verify: test
  asserting required keys per item, `span` length ≤ 200, and that replaying it produces candidates the
  normalizer accepts.

## 3. Run store

- [x] 3.1 `app/runs.py`: create / get / dispose a run keyed by `thread_id`, with one `asyncio.Lock`
  per run and a stable way to address it. Verify: `tests/test_runs.py` covers create → get → dispose,
  and that getting an unknown id raises the error the API maps to `404 unknown_run`.
- [x] 3.2 Concurrent triggers on one run serialise. Verify: test firing two chains concurrently and
  asserting both contributions appear in `trail` / `stages` — nothing lost, nothing interleaved
  (use `asyncio.run` inside a sync test, no new test dependency).

## 4. HTTP API

- [x] 4.1 `app/api/envelope.py::to_envelope(state)` returns `thread_id`, `business_type`, `fields`,
  `extra_fields`, `findings`, `stages`, `trail`, `_candidates`, `supported_stages`. Verify: test
  asserting every key and that `supported_stages == sorted(STAGE_TARGETS)`.
- [x] 4.2 `POST /runs` accepts multipart files and/or a `text` field; text is written to
  `runs/<thread_id>/pasted.txt` and registered as a `text/plain` `SourceFile`. Verify: TestClient test
  asserting the echo of `files`, and that parsing the pasted text yields blocks with `page`/`bbox` null.
- [x] 4.3 `POST /runs` with neither files nor text → `400 EMPTY_SUBMISSION`, no run created. Verify:
  test asserting the code and that the store did not grow.
- [x] 4.4 `POST /runs/{thread_id}/stages/{stage}` executes the declared chain and returns the envelope
  with one report per executed stage, in order. Verify: test on a fresh run triggering `normalize` and
  asserting the report order `parse, extract, normalize`.
- [x] 4.5 Error mapping: `unknown_stage` → 409, `missing_prerequisite` → 409 `REFUSED` with `missing`,
  a non-standalone agent → 403 `NOT_STANDALONE` (checked before the plan lookup), unknown run → 404
  `unknown_run`. Verify: parametrised TestClient test covering all four.
- [x] 4.6 `GET /runs/{thread_id}` returns the envelope; when `stages` cannot be assembled the response
  is `500 INCOMPLETE_RESULT`, never a 200 with empty `stages`. Verify: test with a run whose state was
  monkeypatched to drop `stages`.
- [x] 4.7 One error body shape `{code, message, detail?}` via exception handlers. Verify: test asserting
  the body keys for every code produced in 4.3–4.6.

## 5. Hygiene and docs

- [x] 5.1 `.gitignore` covers `runs/`. Verify: after running the API tests, `git status --porcelain`
  shows no run artefacts.
- [x] 5.2 `pyproject.toml`: dependencies gain `python-multipart` (multipart uploads), dev extra gains
  `httpx` (TestClient). Verify: `~/.local/bin/uv pip install --python .venv/bin/python -e '.[dev]'`
  succeeds and `.venv/bin/python -c "from fastapi.testclient import TestClient"` works.
- [x] 5.3 README: a short "HTTP API" section with the server command, the three endpoints and one `curl`
  example each, plus the `SMART_EDIT_LLM` values. Verify: every command in the section runs as written
  against a locally started server.

## 6. Acceptance

- [x] 6.1 Fixture-provider end-to-end: create a run from text, trigger `normalize`, and assert non-empty
  `fields`, ordered `stages`, non-empty `trail`, and zero `summarize`/`rewrite`/`drop` entries. Verify:
  pytest via TestClient.
- [x] 6.2 Honesty end-to-end: with `SMART_EDIT_LLM` unset, `extract` is `failed`, `_candidates` is empty
  and `fields` contains only `missing` placeholders. Verify: pytest asserting exactly that.
- [x] 6.3 Refusal end-to-end: `agent4` → `403 NOT_STANDALONE`, an unregistered stage → `409
  unknown_stage`, an unknown `thread_id` → `404 unknown_run`, empty submission → `400 EMPTY_SUBMISSION`.
  Verify: parametrised pytest asserting the codes.

## Workflow follow-up

- `editor-shell` consumes these three endpoints; any envelope change updates `console-api` first.
- When `poc-skeleton` §8/§9 land: replace `execute_chain`'s internals with a graph invoke, drop the
  per-run lock, and add `POST /runs/{tid}/resume` plus `GET /runs/{tid}/events` in that change.
- Decide design Open Question 1 (`openspec/config.yaml` says `zh`, these artifacts are English) — the
  flip affects all three owners.
- Archive with `/opsx-archive` once 6.1–6.3 pass and `editor-shell` has confirmed it can consume the
  envelope.