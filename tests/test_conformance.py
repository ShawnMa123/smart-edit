"""Template-conformance audit: config, redaction, model validation and the end-to-end service."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.conformance.compose import (
    ComposeError,
    ComposedResult,
    Composition,
    ConformanceComposer,
    locate_quote,
    merge_compositions,
)
from app.conformance.config import ConfigError, get_config, load_config, load_configs
from app.conformance.contracts import ConformanceRequest
from app.conformance.redact import REDACTED, redact_blocks
from app.conformance.service import ConformanceService, Settings
from app.conformance.store import ConformanceStore
from app.documents.projection import plain_text_document

SAMPLE = Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")


# ── fixtures ──────────────────────────────────────────────────────────────────
class FakeGateway:
    label = "doubao:test-model"

    def __init__(self, response: dict | None = None, *, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[dict] = []

    def compose_json(self, system: str, payload: dict, *, timeout: float | None = None) -> dict:
        self.calls.append({"system": system, "payload": payload, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


class FakeDocuments:
    def __init__(self, view: dict) -> None:
        self.view = view
        self.requested: list[str] = []

    def document_view(self, principal, document_id: str) -> dict:  # noqa: ANN001 - principal unused
        self.requested.append(document_id)
        if document_id != self.view["document_id"]:
            raise _NotFound()
        return self.view


class _NotFound(Exception):
    status = 404
    code = "document_not_found"


def make_view(
    text: str, *, revision: int = 1, sha: str = "a" * 64, document_id: str = "doc-1"
) -> dict:
    return {
        "document_id": document_id,
        "draft_id": "draft-1",
        "title": "Demand guarantee",
        "revision": revision,
        "content": plain_text_document(text),
        "text": text,
        "content_sha256": sha,
    }


def make_service(
    response: dict | None = None,
    *,
    approved: bool = True,
    gateway=None,
    text=SAMPLE,
    config_dir: str | None = None,
):
    composer = ConformanceComposer(
        gateway or FakeGateway(response or {"results": [], "summary": ""}), approved=approved
    )
    return ConformanceService(
        documents=FakeDocuments(make_view(text)),
        composer=composer,
        store=ConformanceStore(":memory:"),
        settings=Settings(),
        config_dir=config_dir,
    )


def review(service: ConformanceService, config_id: str = "guarantee-standard", **request_kwargs):
    request = ConformanceRequest(
        workspace_id="ws_demo_01", document_id="doc-1", config_id=config_id, **request_kwargs
    )
    run, needs_run = service.submit(request)
    assert needs_run is True
    service.execute(run.run_id, request)
    finished = service.get_run(run.run_id)
    report = service.get_report(finished.report_id or "")
    return finished, report


def pass_all(config_id: str = "guarantee-standard") -> dict:
    config = get_config(config_id)
    return {
        "summary": "Read the document.",
        "results": [
            {
                "id": requirement.id,
                "status": "pass",
                "explanation": "Present.",
                "quote": "",
                "confidence": "high",
            }
            for requirement in config.requirements
        ],
    }


# ── config ────────────────────────────────────────────────────────────────────
def test_published_configs_load_with_a_stable_fingerprint():
    configs = load_configs()
    ids = [config.config_id for config in configs]
    assert "guarantee-standard" in ids
    assert "guarantee-strict" in ids

    first = load_config("app/configs/conformance/guarantee-standard.yaml")
    second = load_config("app/configs/conformance/guarantee-standard.yaml")
    assert first.content_sha256 == second.content_sha256
    assert first.extraction_profile == "guarantee-default"
    assert "rules.urdg_758" in first.requirement_ids
    assert first.generation.max_document_chars >= 1000


def test_unknown_config_is_refused_instead_of_falling_back():
    with pytest.raises(ConfigError):
        get_config("no-such-config")


def test_config_detail_exposes_requirements_and_limits():
    service = make_service(pass_all())

    detail = service.config_detail("guarantee-standard")

    assert detail.config_id == "guarantee-standard"
    assert detail.requirement_count == len(detail.requirements)
    assert {item.id for item in detail.requirements} >= {"rules.urdg_758", "parties.legal_names"}
    assert detail.extraction_profile == "guarantee-default"
    assert detail.generation["chunk_chars"] >= 500
    assert "guarantee_amount" in detail.required_fields


def test_config_without_any_requirement_is_invalid(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text(
        "config_id: empty\nversion: 1.0.0\npublished: true\nname: Empty\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(path)


# ── redaction ─────────────────────────────────────────────────────────────────
def test_redaction_masks_identifiers_and_only_reports_masked_samples():
    blocks = [
        {
            "i": 0,
            "text": "Please pay to account 6123 4567 8901 2345, contact ops@example.com "
            "or +65 6123 4567. Card 4111-1111-1111-1111. IBAN GB82WEST12345698765432.",
        }
    ]
    outcome = redact_blocks(blocks, mode="basic")

    assert outcome.applied is True
    assert outcome.total >= 4
    kinds = {step.kind for step in outcome.steps}
    assert {"email", "card", "account_or_phone"} <= kinds
    masked = outcome.blocks[0]["text"]
    assert REDACTED in masked
    assert "ops@example.com" not in masked
    assert "4111-1111-1111-1111" not in masked
    for step in outcome.steps:
        assert "•" in step.sample or step.sample == REDACTED
        assert "ops@example.com" != step.sample


def test_redaction_off_leaves_the_text_unchanged():
    blocks = [{"i": 0, "text": "account 6123456789012345"}]
    outcome = redact_blocks(blocks, mode="off")

    assert outcome.applied is False
    assert outcome.blocks[0]["text"] == "account 6123456789012345"


# ── composer validation ───────────────────────────────────────────────────────
def test_quote_must_be_locatable_in_the_document():
    blocks = [{"i": 3, "text": "Governing Rules: URDG 758"}]
    assert locate_quote("Governing Rules: URDG 758", blocks) == 3
    assert locate_quote("subject to URDG 758", blocks) is None


def test_composer_downgrades_a_finding_without_a_real_quote():
    config = get_config("guarantee-standard")
    composer = ConformanceComposer(
        FakeGateway(
            {
                "results": [
                    {
                        "id": "rules.urdg_758",
                        "status": "finding",
                        "explanation": "The rules look wrong.",
                        "quote": "this sentence is not in the document",
                    }
                ]
            }
        ),
        approved=True,
    )
    composition = composer.review(
        config=config,
        blocks=[{"i": 0, "text": SAMPLE}],
        known_fields={},
        language="en",
        document={},
    )

    by_id = {item.id: item for item in composition.results}
    assert by_id["rules.urdg_758"].status == "unable_to_assess"
    assert "evidence_not_locatable" in by_id["rules.urdg_758"].reason_codes
    assert by_id["parties.legal_names"].status == "unable_to_assess"
    assert "model_omitted" in by_id["parties.legal_names"].reason_codes


def test_composer_ignores_an_invented_requirement_id():
    config = get_config("guarantee-standard")
    composer = ConformanceComposer(
        FakeGateway(
            {"results": [{"id": "invented.requirement", "status": "pass", "explanation": "ok"}]}
        ),
        approved=True,
    )
    composition = composer.review(
        config=config,
        blocks=[{"i": 0, "text": SAMPLE}],
        known_fields={},
        language="en",
        document={},
    )

    assert {item.id for item in composition.results} == set(config.requirement_ids)
    assert all(item.status == "unable_to_assess" for item in composition.results)


def test_unapproved_composer_is_unavailable():
    composer = ConformanceComposer(FakeGateway({}), approved=False)
    assert composer.available is False
    with pytest.raises(ComposeError) as exc:
        composer.review(
            config=get_config("guarantee-standard"),
            blocks=[],
            known_fields={},
            language="en",
            document={},
        )
    assert exc.value.code == "composer_unavailable"


# ── service ───────────────────────────────────────────────────────────────────
def test_review_reads_the_sample_and_reports_no_missing_field():
    service = make_service(pass_all())
    run, report = review(service)

    assert run.status == "succeeded"
    assert report.snapshot.revision == 1
    assert report.snapshot.content_sha256 == "a" * 64
    assert report.missing_fields == []
    assert report.provenance.extraction_status == "deterministic"
    assert report.counts.requirements == len(get_config("guarantee-standard").requirements)
    assert report.counts.passed == report.counts.requirements
    assert report.outcome == "no_findings"
    assert report.completion == "complete"
    assert report.provenance.model == "doubao:test-model"
    assert report.provenance.model_calls == 1


def test_review_reports_missing_fields_for_a_document_without_them():
    service = make_service(pass_all(), text="333333")
    run, report = review(service)

    assert run.status == "succeeded"
    missing = {field.key for field in report.missing_fields}
    assert {"applicant_name", "guarantee_amount", "expiry_date"} <= missing
    assert report.counts.missing_fields == len(missing)
    assert report.outcome == "needs_input"


def test_stale_revision_is_refused_not_silently_re_read():
    service = make_service(pass_all())
    request = ConformanceRequest(
        workspace_id="ws_demo_01",
        document_id="doc-1",
        config_id="guarantee-standard",
        expected_revision=7,
    )
    run, _ = service.submit(request)
    service.execute(run.run_id, request)

    finished = service.get_run(run.run_id)
    assert finished.status == "failed"
    assert finished.error == "stale_snapshot"


def test_unavailable_model_leaves_every_requirement_unassessed():
    service = make_service(pass_all(), approved=False)
    run, report = review(service)

    assert run.status == "succeeded"
    assert {item.status for item in report.results} == {"unable_to_assess"}
    assert report.outcome == "unable_to_assess"
    assert report.completion == "partial"
    assert any(item["code"] == "composer_unavailable" for item in report.limitations)


def test_model_findings_never_escalate_beyond_warning():
    response = {
        "summary": "A gap.",
        "results": [
            {
                "id": "rules.urdg_758",
                "status": "finding",
                "explanation": "The document names another rule set.",
                "quote": "Governing Rules: URDG 758",
                "suggestion": "Keep URDG 758.",
                "confidence": "high",
            }
        ],
    }
    service = make_service(response)
    _, report = review(service)

    by_id = {item.id: item for item in report.results}
    assert by_id["rules.urdg_758"].status == "finding"
    assert by_id["rules.urdg_758"].severity == "Warning"
    assert by_id["rules.urdg_758"].gate_type == "human_review"
    assert by_id["rules.urdg_758"].block_index is not None
    assert report.outcome == "findings_present"


def test_redaction_steps_are_reported_for_the_model_payload():
    text = SAMPLE + "\n\nPlease remit to 6123 4567 8901 2345 and mail ops@example.com."
    gateway = FakeGateway(pass_all())
    service = make_service(pass_all(), gateway=gateway, text=text)
    _, report = review(service)

    assert report.provenance.redaction.applied is True
    assert report.provenance.redaction.steps
    sent = gateway.calls[0]["payload"]["document"]["blocks"]
    assert any(REDACTED in block["text"] for block in sent)
    assert not any("ops@example.com" in block["text"] for block in sent)


# ── chunking ──────────────────────────────────────────────────────────────────
MINI_CONFIG = """
config_id: mini
version: 1.0.0
published: true
name: Mini
document_types: [guarantee]
fields:
  required: []
requirements:
  - id: r.one
    title: One requirement
    level: must
generation:
  max_document_chars: 1000
  chunk_chars: 500
  max_findings: 3
"""


class ChunkGateway:
    """Echoes the first block of each chunk as a quote, so the merge has real evidence."""

    label = "doubao:chunk-test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def compose_json(self, system: str, payload: dict, *, timeout=None) -> dict:  # noqa: ANN001
        self.calls.append(payload)
        block = payload["document"]["blocks"][0]
        return {
            "summary": f"chunk {payload['document']['chunk_index']}",
            "results": [
                {
                    "id": "r.one",
                    "status": "pass",
                    "explanation": "Seen in this chunk.",
                    "quote": block["text"][:20],
                    "confidence": "high",
                }
            ],
        }


def test_long_document_is_chunked_and_merged(tmp_path):
    (tmp_path / "mini.yaml").write_text(MINI_CONFIG, encoding="utf-8")
    paragraphs = "\n\n".join(f"paragraph {index} " + ("x" * 90) for index in range(8))
    gateway = ChunkGateway()
    service = make_service(gateway=gateway, text=paragraphs, config_dir=str(tmp_path))

    run, report = review(service, config_id="mini")

    assert run.status == "succeeded"
    assert len(gateway.calls) > 1, "the document should span several chunks"
    assert report.provenance.model_calls == len(gateway.calls)
    assert any(item["code"] == "document_chunked" for item in report.limitations)
    assert {item.status for item in report.results} == {"pass"}
    assert (
        gateway.calls[0]["document"]["chunk_count"]
        == gateway.calls[-1]["document"]["chunk_count"]
        == len(gateway.calls)
    )
    for payload in gateway.calls:
        # every payload stays inside the per-call budget
        assert sum(len(block["text"]) for block in payload["document"]["blocks"]) <= 520


def test_document_beyond_the_budget_is_truncated_and_says_so(tmp_path):
    (tmp_path / "mini.yaml").write_text(MINI_CONFIG, encoding="utf-8")
    paragraphs = "\n\n".join(f"paragraph {index} " + ("x" * 90) for index in range(20))
    gateway = ChunkGateway()
    service = make_service(gateway=gateway, text=paragraphs, config_dir=str(tmp_path))

    _, report = review(service, config_id="mini")

    assert report.snapshot.truncated is True
    assert report.snapshot.analyzed_chars < sum(len(part) for part in paragraphs.split("\n\n"))
    truncated = next(item for item in report.limitations if item["code"] == "document_truncated")
    assert "characters were sent" in truncated["message"]


def test_merge_prefers_finding_then_pass_then_unable():
    def result(status: str, quote: str | None = None) -> ComposedResult:
        return ComposedResult(
            id="r.one",
            status=status,
            explanation=f"{status} explanation",
            quote=quote,
            block_index=1 if quote else None,
            confidence="high" if status != "unable_to_assess" else "low",
            reason_codes=("not_visible",) if status == "unable_to_assess" else (),
        )

    merged = merge_compositions(
        [
            Composition(
                summary="first",
                results=(result("unable_to_assess"),),
                notes=["a"],
                model="m",
                calls=1,
            ),
            Composition(
                summary="second",
                results=(result("pass", "quoted pass"),),
                notes=["b"],
                model="m",
                calls=1,
            ),
            Composition(
                summary="",
                results=(result("finding", "quoted finding"),),
                notes=[],
                model="m",
                calls=1,
            ),
        ]
    )

    assert merged.calls == 3
    assert merged.summary == "first"
    assert merged.notes == ("a", "b")
    assert [item.status for item in merged.results] == ["finding"]
    assert merged.results[0].quote == "quoted finding"

    only_pass = merge_compositions(
        [
            Composition("", (result("unable_to_assess"),), (), "m", 1),
            Composition("", (result("pass", "quoted pass"),), (), "m", 1),
        ]
    )
    assert only_pass.results[0].status == "pass"
    assert only_pass.results[0].quote == "quoted pass"

    none_visible = merge_compositions(
        [
            Composition("", (result("unable_to_assess"),), (), "m", 1),
            Composition("", (result("unable_to_assess"),), (), "m", 1),
        ]
    )
    assert none_visible.results[0].status == "unable_to_assess"
    assert none_visible.results[0].quote is None


# ── HTTP surface ──────────────────────────────────────────────────────────────
def test_http_surface_lists_configs_and_runs_a_review():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.api.conformance import router
    from app.api.errors import ApiFailure

    service = make_service(pass_all())
    app = FastAPI()
    app.include_router(router)
    app.state.conformance = service

    @app.exception_handler(ApiFailure)
    async def _api_failure(_request, exc: ApiFailure):  # noqa: ANN001 - FastAPI signature
        return JSONResponse(
            status_code=exc.status, content={"code": exc.code, "message": exc.message}
        )

    client = TestClient(app)

    configs = client.get("/conformance/configs")
    assert configs.status_code == 200
    assert any(item["config_id"] == "guarantee-standard" for item in configs.json())

    detail = client.get("/conformance/configs/guarantee-standard")
    assert detail.status_code == 200, detail.text
    assert detail.json()["requirements"][0]["id"]
    assert detail.json()["requirement_count"] == len(detail.json()["requirements"])

    missing = client.get("/conformance/configs/nope")
    assert missing.status_code == 400
    assert missing.json()["code"] == "unknown_config"

    created = client.post(
        "/conformance/reviews",
        json={
            "workspace_id": "ws_demo_01",
            "document_id": "doc-1",
            "config_id": "guarantee-standard",
        },
    )
    assert created.status_code == 202, created.text
    run = created.json()
    assert run["status"] in {"queued", "succeeded"}
    assert run["report_id"]

    report = client.get(f"/conformance/reports/{run['report_id']}")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["outcome"] == "no_findings"
    assert body["config"]["config_id"] == "guarantee-standard"
    assert body["provenance"]["prompt_version"].startswith("conformance/")