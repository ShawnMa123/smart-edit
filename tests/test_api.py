"""HTTP API (tasks 4.1-4.7) and acceptance (tasks 6.1-6.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.envelope import to_envelope
from app.api.errors import IncompleteResult
from app.api.main import create_app
from app.llm import resolve_llm
from app.runs import RunStore
from app.state import OVERREACH_OPS
from app.stages import STAGE_TARGETS

FIXTURE = Path("fixtures/llm/extract_sample.json")
SAMPLE_TEXT = Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")
ENVELOPE_KEYS = (
    "thread_id",
    "business_type",
    "files",
    "fields",
    "extra_fields",
    "findings",
    "stages",
    "trail",
    "_candidates",
    "documents",
    "verification",
    "gate",
    "supported_stages",
)


def _build(tmp_path, *, provider: bool = True):
    llm = resolve_llm(f"fixture:{FIXTURE}") if provider else None
    store = RunStore(runs_dir=tmp_path / "runs")
    return TestClient(create_app(store=store, llm=llm)), store


@pytest.fixture
def api(tmp_path):
    return _build(tmp_path)


def _new_run(client: TestClient, text: str = SAMPLE_TEXT) -> str:
    response = client.post("/runs", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def test_envelope_carries_every_required_key(api):
    """4.1 The envelope is the client contract."""
    client, _ = api
    body = client.get(f"/runs/{_new_run(client)}").json()

    for key in ENVELOPE_KEYS:
        assert key in body, f"envelope is missing {key}"
    assert body["supported_stages"] == sorted(STAGE_TARGETS)
    assert body["supported_stages"] == ["audit", "extract", "normalize", "parse"]


def test_envelope_refuses_to_omit_stages():
    """4.1 / 4.6 A state without `stages` never serialises as a clean run."""
    with pytest.raises(IncompleteResult):
        to_envelope({"run_id": "R-1"})


def test_the_envelope_carries_the_imported_documents(api):
    """0.2 `documents` is how the editor gets its text; `[]` means "nothing parsed yet"."""
    client, _ = api
    thread_id = _new_run(client)

    before = client.get(f"/runs/{thread_id}").json()
    after = client.post(f"/runs/{thread_id}/stages/parse").json()

    assert before["documents"] == [], "an unparsed run must not fabricate text"
    assert len(after["documents"]) == 1
    document = after["documents"][0]
    assert set(document) == {"file_id", "filename", "form", "errors", "full_text", "rich"}
    assert document["form"] == "plain_text"
    assert document["errors"] == []
    assert document["full_text"].strip(), "the parsed text is what the editor shows"
    assert "blocks" not in document, "blocks stay server-side until a screen needs them"
    # `rich-text-editor`: plain text has no structure to infer, so it degrades and says so.
    assert document["rich"]["type"] == "doc"
    assert document["rich"]["provenance"] == "fallback"
    assert document["rich"]["content"], "a readable file still renders as paragraphs"


def test_create_run_from_text(api):
    """4.2 Pasted text becomes one text/plain source file."""
    client, store = api
    response = client.post("/runs", json={"text": SAMPLE_TEXT})

    assert response.status_code == 201
    body = response.json()
    assert body["thread_id"].startswith("R-")
    assert len(body["files"]) == 1
    assert body["files"][0]["mime"] == "text/plain"
    assert body["files"][0]["filename"] == "pasted.txt"
    assert body["stages"] == [], "a fresh run has no stage reports yet"

    client.post(f"/runs/{body['thread_id']}/stages/parse")
    blocks = store.get(body["thread_id"])["docs"][0]["blocks"]
    assert blocks, "text must be parsed"
    assert all(block["page"] is None and block["bbox"] is None for block in blocks)


def test_create_run_from_multipart_files(api):
    """4.2 Multipart upload is accepted and echoed with a digest."""
    client, _ = api
    response = client.post(
        "/runs",
        files={"files": ("sample_document.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201, response.text
    files = response.json()["files"]
    assert [item["filename"] for item in files] == ["sample_document.txt"]
    assert len(files[0]["sha256"]) == 64


def test_empty_submission_is_refused_and_creates_nothing(api):
    """4.3 No files and no text is a refusal, not an empty run."""
    client, store = api
    response = client.post("/runs", json={})

    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_SUBMISSION"
    assert len(store) == 0


def test_trigger_stage_executes_the_declared_chain(api):
    """4.4 `normalize` backfills parse and extract, in order."""
    client, _ = api
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/normalize").json()

    assert [report["stage"] for report in body["stages"]] == ["parse", "extract", "normalize"]
    assert [report["status"] for report in body["stages"]] == ["done", "done", "done"]


def test_retriggering_after_normalize_is_refused_not_degraded(api):
    """4.4 A second `normalize` is refused (candidates are gone) and changes nothing.

    `normalize` clears `_candidates`, so `plan_standalone` refuses the repeat instead of rebuilding
    `fields` from nothing. Clients re-audit by creating a new run.
    """
    client, _ = api
    thread_id = _new_run(client)
    first = client.post(f"/runs/{thread_id}/stages/normalize").json()

    second = client.post(f"/runs/{thread_id}/stages/normalize")

    assert second.status_code == 409
    assert second.json()["code"] == "REFUSED"
    assert second.json()["detail"]["missing"] == ["_candidates"]

    after = client.get(f"/runs/{thread_id}").json()
    assert after["fields"] == first["fields"], "the refused repeat must not degrade the result"
    assert after["stages"] == first["stages"]


def test_retriggering_a_done_stage_is_reuse(api):
    """4.4 Re-running `parse` reuses the existing report instead of re-parsing."""
    client, _ = api
    thread_id = _new_run(client)
    first = client.post(f"/runs/{thread_id}/stages/parse").json()

    second = client.post(f"/runs/{thread_id}/stages/parse").json()

    assert second["stages"] == first["stages"], "the done report is reused verbatim"
    assert len(second["stages"]) == 1, "no second parse report is appended"
    assert second["trail"] == first["trail"], "a skipped stage writes nothing"


def test_agent4_is_standalone_through_the_audit_target(tmp_path):
    """0.2 / 6.2 `agent4` flipped to standalone: the agent id resolves to the registered `audit` target."""
    client, _ = _build(tmp_path)
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/agent4").json()

    assert [report["stage"] for report in body["stages"]] == [
        "parse",
        "extract",
        "normalize",
        "audit",
    ]
    assert body["verification"]["audit"]["planned"] == 51


def test_a_non_standalone_agent_is_still_403(tmp_path, monkeypatch):
    """4.5 The refusal survives for any agent that is not registered as standalone.

    No agent in this build is non-standalone any more (0.2 flipped `agent4`), so the branch is
    exercised by injecting one — the rule still has to hold for the next agent that registers.
    """
    from app.api import main as api_main
    from app.stages import AgentSpec

    monkeypatch.setitem(
        api_main.AGENT_SPECS, "agent9", AgentSpec("agent1", (), (), (), False)
    )
    client, _ = _build(tmp_path)
    thread_id = _new_run(client)

    response = client.post(f"/runs/{thread_id}/stages/agent9")

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_STANDALONE"
    assert response.json()["detail"]["agent"] == "agent9"
    assert "agent9" not in STAGE_TARGETS


def test_unregistered_stage_is_409(tmp_path):
    """4.5 An unregistered target lists what is valid."""
    client, _ = _build(tmp_path)
    thread_id = _new_run(client)

    response = client.post(f"/runs/{thread_id}/stages/summarize")

    assert response.status_code == 409
    assert response.json()["code"] == "unknown_stage"
    assert response.json()["detail"]["registered"] == sorted(STAGE_TARGETS)


def test_missing_prerequisite_is_REFUSED(tmp_path):
    """4.5 A run without files cannot be parsed; the refusal names the missing key."""
    client, store = _build(tmp_path)
    thread_id = _new_run(client)
    store.get(thread_id)["files"] = []

    response = client.post(f"/runs/{thread_id}/stages/parse")

    assert response.status_code == 409
    assert response.json()["code"] == "REFUSED"
    assert response.json()["detail"]["missing"] == ["files"]


def test_unknown_run_is_404(tmp_path):
    """4.5 A vanished run is an error, never an empty run."""
    client, _ = _build(tmp_path)

    for response in (client.get("/runs/R-nope"), client.post("/runs/R-nope/stages/parse")):
        assert response.status_code == 404
        assert response.json()["code"] == "unknown_run"


def test_incomplete_result_is_500(tmp_path):
    """4.6 A state that lost `stages` must not answer 200."""
    client, store = _build(tmp_path)
    thread_id = _new_run(client)
    store.get(thread_id).pop("stages")

    response = client.get(f"/runs/{thread_id}")

    assert response.status_code == 500
    assert response.json()["code"] == "INCOMPLETE_RESULT"


def test_every_error_body_has_code_and_message(tmp_path):
    """4.7 One body shape for every refusal."""
    client, store = _build(tmp_path)
    thread_id = _new_run(client)

    responses = [
        client.post("/runs", json={}),
        client.get("/runs/R-nope"),
        client.post(f"/runs/{thread_id}/stages/agent2"),
        client.post(f"/runs/{thread_id}/stages/summarize"),
    ]
    store.get(thread_id)["files"] = []
    responses.append(client.post(f"/runs/{thread_id}/stages/parse"))

    for response in responses:
        body = response.json()
        assert set(body) >= {"code", "message"}, body
        assert isinstance(body["code"], str) and body["code"]
        assert isinstance(body["message"], str) and body["message"]


def test_fixture_audit_end_to_end(api):
    """6.1 A full audit over HTTP: fields, ordered stages, trail, no overreach."""
    client, _ = api
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/normalize").json()

    assert body["fields"], "the fixture yields real fields"
    assert body["fields"]["guarantee_amount"]["value"] == "500000.00"
    assert body["fields"]["guarantee_amount"]["status"] == "extracted"
    assert [report["stage"] for report in body["stages"]] == ["parse", "extract", "normalize"]
    assert body["trail"], "every run is traceable"
    assert not OVERREACH_OPS & {entry["op"] for entry in body["trail"]}
    assert body["_candidates"] == [], "normalize clears the temporary channel"
    assert "fixture:" in body["stages"][1]["reason"], "a fixture run must say so"


def test_no_provider_is_reported_not_faked(tmp_path):
    """6.2 With no provider the audit says the field checks did not run."""
    client, _ = _build(tmp_path, provider=False)
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/normalize").json()
    extract = body["stages"][1]

    assert extract["stage"] == "extract"
    assert extract["status"] == "failed"
    assert "no model provider configured" in extract["reason"]
    assert body["_candidates"] == []
    assert body["fields"], "normalize still placeholders the required fields"
    assert {value["status"] for value in body["fields"].values()} == {"missing"}


def test_refusal_codes_end_to_end(tmp_path):
    """6.3 The documented refusals, over HTTP."""
    client, store = _build(tmp_path)
    thread_id = _new_run(client)

    assert client.post("/runs", json={}).json()["code"] == "EMPTY_SUBMISSION"
    assert client.post(f"/runs/{thread_id}/stages/agent2").json()["code"] == "unknown_stage"
    assert client.post(f"/runs/{thread_id}/stages/bogus").json()["code"] == "unknown_stage"
    assert client.get("/runs/R-nope").json()["code"] == "unknown_run"
    store.get(thread_id)["files"] = []
    assert client.post(f"/runs/{thread_id}/stages/parse").json()["code"] == "REFUSED"


def test_audit_stage_over_http(api):
    """6.2 `POST /stages/audit` backfills the shared layer and returns the envelope."""
    client, _ = api
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/audit").json()

    assert [report["stage"] for report in body["stages"]] == [
        "parse",
        "extract",
        "normalize",
        "audit",
    ]
    assert [report["status"] for report in body["stages"]] == ["done"] * 4
    audit_stage = body["stages"][-1]
    assert audit_stage["agent"] == "agent4"
    assert audit_stage["model_calls"] == 0

    verification = body["verification"]
    assert len(verification["checks"]) == 51, "one Issue per planned unit"
    assert verification["audit"]["planned"] == 51
    assert verification["audit"]["engine_version"] == "1.0.0"
    assert verification["audit"]["bundle_versions"] == {"guarantee-core": "1.0.0"}
    assert verification["verdict"] in ("pass", "warn", "fail")
    assert verification["score"] is None, "score is display-only and never computed here"


def test_verification_and_gate_are_null_until_asked(api):
    """6.3 Both keys exist before an audit, and `null` never means clean."""
    client, _ = api
    thread_id = _new_run(client)

    body = client.get(f"/runs/{thread_id}").json()

    assert body["verification"] is None
    assert body["gate"] is None


def test_an_audit_alone_never_approves_anything(api):
    """6.3 The audit decides no operation: `gate` stays null until one is asked about."""
    client, _ = api
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/audit").json()

    assert body["verification"]["audit"]["outcome"]
    assert body["gate"] is None


def test_audit_over_http_keeps_the_console_contract(tmp_path):
    """6.3 Adding the audit surfaces breaks no existing console-api expectation."""
    client, _ = _build(tmp_path)
    thread_id = _new_run(client)

    body = client.post(f"/runs/{thread_id}/stages/normalize").json()

    assert body["verification"] is None, "normalize does not audit"
    assert body["gate"] is None
    assert body["findings"] == [] or isinstance(body["findings"], list)
    assert not OVERREACH_OPS & {entry["op"] for entry in body["trail"]}