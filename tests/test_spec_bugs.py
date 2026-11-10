"""Executable regressions for spec violations found by the audit test design.

Every test here asserts the behaviour the OpenSpec text requires. They were written as strict
`xfail` reproductions; each defect has since been fixed, so they now run as ordinary regression
tests and fail loudly if the behaviour comes back. Each test names the spec scenario and the
original observed implementation.

Run just these with:

    .venv/Scripts/python.exe -m pytest tests/test_spec_bugs.py -q
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.audit.bind import bind_field
from app.audit.report import AuditReportError, summarise
from app.audit.runner import audit_state
from app.audit.snapshot import snapshot_digest
from app.nodes.audit import audit_node
from app.nodes.export import export_node
from app.nodes.gate import gate_node
from app.nodes.pipeline_gate import evaluate_export_gate
from app.parsing.normalize import build_fields, decide_business_type
from app.regulatory.answer import LLMAnswerer
from app.regulatory.cite_check import cite_check
from app.regulatory.node import regulatory_node
from app.regulatory.retriever import FakeRetriever
from app.rules.engine import evaluate_schema_check
from app.rules.schema import load_schema
from app.rules.types import PASS, CheckResult, Unit
from app.runtime import merge_update
from app.stages import stage_report
from app.storage.doc_versions import DocVersionStore


# ---------------------------------------------------------------------------
# Local fixtures (kept independent of other test modules)
# ---------------------------------------------------------------------------


def _field(key: str, value: str, *, status: str = "extracted", page: int | None = 1) -> dict:
    return {
        "key": key,
        "value": value,
        "status": status,
        "confirmed": False,
        "edited_by_user": False,
        "source": {
            "file_id": "F-1",
            "page": page,
            "bbox": None,
            "span": value,
            "form_label": None,
        }
        if status == "extracted"
        else None,
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Beta Construction Ltd",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}
DOCUMENT = "DEMAND GUARANTEE\n" + "\n".join(f"{key}: {value}" for key, value in VALUES.items())


def _state(**overrides) -> dict:
    state = {
        "run_id": "R-bug",
        "files": [
            {
                "file_id": "F-1",
                "filename": "g.txt",
                "mime": "text/plain",
                "path": "p",
                "sha256": "a" * 64,
            }
        ],
        "docs": [
            {
                "file_id": "F-1",
                "filename": "g.txt",
                "form": "plain_text",
                "blocks": [
                    {
                        "file_id": "F-1",
                        "page": None,
                        "bbox": None,
                        "text": DOCUMENT,
                        "kind": "paragraph",
                    }
                ],
                "full_text": DOCUMENT,
                "errors": [],
            }
        ],
        "fields": {key: _field(key, value) for key, value in VALUES.items()},
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "agent": "agent1", "stage": "parse", "op": "read"}],
        "stages": [],
    }
    state.update(overrides)
    return state


def _blocks_doc(*blocks: dict) -> dict:
    return {
        "file_id": "F-1",
        "filename": "g.pdf",
        "form": "pdf_text",
        "blocks": list(blocks),
        "full_text": "\n".join(block["text"] for block in blocks),
        "errors": [],
    }


def _block(text: str, page: int, *, bbox=None) -> dict:
    return {
        "file_id": "F-1",
        "page": page,
        "bbox": bbox or [0, 0, 100, 20],
        "text": text,
        "kind": "paragraph",
    }


def _candidate(key: str, raw: str, span: str, *, page=None) -> dict:
    return {
        "key": key,
        "raw_value": raw,
        "confidence": 0.9,
        "_source": {
            "file_id": "F-1",
            "page": page,
            "bbox": [0, 0, 100, 20] if page else None,
            "span": span,
            "form_label": None,
        },
    }


# ---------------------------------------------------------------------------
# Agent 1 / shared normalization
# ---------------------------------------------------------------------------


def test_a_value_contained_in_one_late_page_block_is_extracted_not_cross_page():
    """agent-normalize / 跨页拼接必须降级: only a genuinely stitched span is cross-page."""
    doc = _blocks_doc(
        _block("保函金额：USD 500K", 1),
        _block("受益人：Adidas AG", 1),
        _block("保函编号：BG-2026-0001", 2),
    )
    result = build_fields(
        [_candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001", page=2)],
        [doc],
        fields_yaml={"guarantee_number": {"label": "Guarantee No", "type": "string", "required": True}},
    )

    field = result.fields["guarantee_number"]
    assert field["status"] == "extracted"
    assert "merged_across_pages" not in field["notes"]


def test_an_extracted_pdf_value_always_has_a_page_even_when_its_block_is_not_the_only_match():
    """agent-normalize / 出处必须能跳回具体页: extracted + PDF must not keep page=None."""
    doc = _blocks_doc(
        _block("保函编号：", 1),
        _block("BG-2026-0001", 1),
    )
    result = build_fields(
        [_candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001")],
        [doc],
        fields_yaml={"guarantee_number": {"label": "Guarantee No", "type": "string", "required": True}},
    )

    field = result.fields["guarantee_number"]
    assert field["status"] == "extracted"
    assert field["source"]["page"] == 1


def test_a_hedged_amount_is_inferred_not_a_confirmed_decimal():
    """agent-normalize / 模糊表述不得被确定化."""
    text = "金额：约 USD 500K"
    doc = _blocks_doc(_block(text, 1))
    result = build_fields(
        [_candidate("guarantee_amount", "约 USD 500K", "约 USD 500K", page=1)],
        [doc],
        fields_yaml={"guarantee_amount": {"label": "Amount", "type": "amount", "required": True}},
    )

    field = result.fields["guarantee_amount"]
    assert field["status"] == "inferred"
    assert field["value"] != "500000.00"


def test_full_width_guarantee_wording_is_detected_as_guarantee():
    """agent-contract / 定位基准唯一: typographically identical text must decide the same way."""
    decision = decide_business_type(
        [{"file_id": "F-1", "full_text": "ＢＡＮＫ ＧＵＡＲＡＮＴＥＥ", "blocks": []}]
    )

    assert decision.business_type == "guarantee"


@pytest.mark.parametrize("raw", ["-Infinity", "+Infinity", "1e999999999"])
def test_a_non_finite_or_huge_amount_is_downgraded_not_allowed_to_crash(raw):
    """agent-normalize / 值规范化: a malformed number must become a Finding, never an exception."""
    doc = _blocks_doc(_block(f"金额：{raw}", 1))
    result = build_fields(
        [_candidate("guarantee_amount", raw, raw, page=1)],
        [doc],
        fields_yaml={"guarantee_amount": {"label": "Amount", "type": "amount", "required": True}},
    )

    field = result.fields["guarantee_amount"]
    assert field["status"] == "inferred"
    assert any(note for note in field["notes"])


def test_nan_with_a_sign_is_not_a_document_value():
    """agent-normalize / 值规范化: NaN is never a field value, signed or not."""
    doc = _blocks_doc(_block("金额：-NaN", 1))
    result = build_fields(
        [_candidate("guarantee_amount", "-NaN", "-NaN", page=1)],
        [doc],
        fields_yaml={"guarantee_amount": {"label": "Amount", "type": "amount", "required": True}},
    )

    field = result.fields["guarantee_amount"]
    assert field["status"] == "inferred"
    assert field["value"] != "-NaN"


# ---------------------------------------------------------------------------
# Agent 3 / regulatory
# ---------------------------------------------------------------------------


CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["AU", "CN", "US"],
    "built_at": "2026-11-09T00:00:00Z",
}
CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "海关事务担保条例",
    "text": "第464条 保函金额 USD 500,000.00 应当以书面形式约定，适用 URDG 758。",
    "score": 0.91,
    "articles": ["第464条"],
    "effective_from": "2021-01-01",
    "effective_to": None,
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee", "customs"],
}


def _reg_state(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    doc = {
        "file_id": "F-1",
        "filename": "F-1.txt",
        "mime": "text/plain",
        "form": "plain_text",
        "blocks": [
            {"file_id": "F-1", "page": None, "bbox": None, "text": line, "kind": "paragraph"}
            for line in lines
        ],
        "full_text": "\n".join(lines),
        "errors": [],
    }
    return {"docs": [doc], "findings": [], "trail": [], "stages": []}


def test_a_mock_sanctions_hit_in_the_body_is_critical_and_non_blocking_in_raw_mode():
    """regulatory-advice / 疑似命中筛查名单: the body is the only input in raw mode."""
    state = _reg_state("交易对手：SANCTIONED DEMO LTD\n保函编号 BG-2026-0001")
    update = regulatory_node(state, retriever=FakeRetriever([copy.deepcopy(CHUNK)], CORPUS))

    hits = [f for f in update["findings"] if f["rule_id"] == "REG-MOCK-SANCTIONS"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "critical"
    assert hits[0]["blocking"] is False


def test_raw_findings_evidence_is_a_body_fragment():
    """regulatory-advice / raw 模式无字段锚点: evidence must point at the source text."""
    text = "航空器租赁安排，交付地点为境外。"
    state = _reg_state(text)
    update = regulatory_node(state, retriever=FakeRetriever([copy.deepcopy(CHUNK)], CORPUS))

    assert update["findings"], "this document must produce at least one structural finding"
    body = update["legal"]["summary"] + "\n" + text
    for finding in update["findings"]:
        if finding["rule_id"].startswith("REG-"):
            assert finding["evidence"] in text, (finding["rule_id"], finding["evidence"])


def test_llm_legal_conclusions_are_removed_from_summary_and_claims():
    """regulatory-advice / 不替代正式筛查 + 指出问题但不定性."""

    def chat(messages):
        return (
            '{"claims":[{"text":"该保函合规，可做","chunk_id":"chunk-1",'
            '"kind":"applicable_rule"}],"summary":"该保函合规，可以开立。"}'
        )

    state = _reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。")
    update = regulatory_node(
        state,
        retriever=FakeRetriever([copy.deepcopy(CHUNK)], CORPUS),
        answerer=LLMAnswerer(chat, model="fake"),
    )
    legal = update["legal"]
    rendered = legal["summary"] + "\n" + "\n".join(
        str(claim.get("text") or "") for claim in legal["claims"]
    )

    for forbidden in ("合规", "不合规", "可做", "不可做"):
        assert forbidden not in rendered


def test_a_clean_run_still_disclaims_formal_screening():
    """regulatory-advice / 不替代正式筛查: the notice belongs to the result, not only to findings."""
    state = _reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。")
    state["fields"] = {
        "guarantee_amount": {"key": "guarantee_amount", "value": "USD 500,000.00"},
        "applicant_country": {"key": "applicant_country", "value": "CN"},
        "transaction_date": {"key": "transaction_date", "value": "2026-03-15"},
    }
    state["business_type"] = "guarantee"
    state["stages"] = [
        stage_report("normalize", status="done", reason=None, agent="agent1")
    ]
    update = regulatory_node(state, retriever=FakeRetriever([copy.deepcopy(CHUNK)], CORPUS))

    legal = update["legal"]
    assert legal["escalate_to_human"] is False
    assert "不替代正式制裁与出口管制筛查" in legal["summary"]


def test_a_case_changed_claim_is_not_a_verbatim_fragment():
    """regulatory-advice / 有依据的结论: supported means verbatim (normalize_ws does not case-fold)."""
    chunk = {**copy.deepcopy(CHUNK), "text": "ARTICLE 5: ABC TRADING"}
    claims, _ = cite_check(
        [{"text": "article 5: abc trading", "chunk_id": "chunk-1", "support": "supported"}],
        [chunk],
    )

    assert claims[0]["support"] == "insufficient"


def test_a_full_width_claim_is_matched_by_the_shared_benchmark():
    """agent-contract / 归一化基准全层唯一: full-width text points at the same source text."""
    chunk = {**copy.deepcopy(CHUNK), "text": "ARTICLE 5: ABC TRADING"}
    claims, _ = cite_check(
        [{"text": "ＡＲＴＩＣＬＥ ５： ABC TRADING", "chunk_id": "chunk-1", "support": "supported"}],
        [chunk],
    )

    assert claims[0]["support"] == "supported"


def test_a_downgrade_trail_records_the_new_support_state():
    """regulatory-advice / 校验失败降级不删除: the trail must show what the claim became."""
    chunk = {**copy.deepcopy(CHUNK), "text": "article text"}
    _, trail = cite_check(
        [{"text": "not in the chunk", "chunk_id": "chunk-1", "support": "supported"}], [chunk]
    )

    downgrades = [entry for entry in trail if entry["op"] == "transform"]
    assert downgrades
    assert all(entry["after"] == "insufficient" for entry in downgrades)


# ---------------------------------------------------------------------------
# Agent 4 / audit
# ---------------------------------------------------------------------------


def test_a_human_confirmed_inferred_value_passes_the_required_check():
    """rule-audit / Present but unconfirmed: confirmation must clear needs_input (design D7)."""
    schema = load_schema()
    value = bind_field(
        "guarantee_amount",
        {
            "key": "guarantee_amount",
            "value": "500000.00",
            "status": "inferred",
            "confirmed": True,
            "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": "500000.00", "form_label": None},
            "notes": [],
        },
    )
    unit = Unit("SCHEMA:guarantee_amount:required", "schema", field_id="guarantee_amount", required=True)

    result = evaluate_schema_check(unit, schema.fields["guarantee_amount"], value, schema.version)
    assert result.status == PASS


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "1e999999999"])
def test_a_malformed_amount_becomes_a_unit_finding_not_an_audit_crash(raw):
    """rule-audit / Malformed numeric input: the unit reports invalid; the audit survives."""
    state = _state()
    state["fields"]["guarantee_amount"] = _field("guarantee_amount", raw)
    state["docs"][0]["full_text"] = state["docs"][0]["full_text"].replace("500000.00", raw)
    state["docs"][0]["blocks"][0]["text"] = state["docs"][0]["full_text"]

    outcome = audit_state(state, snapshot_digest="d-1")

    assert outcome["report"]["counts"]["failed"] == 0
    assert any(
        result.check_id == "SCHEMA:guarantee_amount:type" and result.status != PASS
        for result in outcome["results"]
    )


def test_the_gate_binds_the_server_snapshot_not_the_digest_the_caller_supplies():
    """rule-audit / The candidate is what gets checked: the server owns the digest."""
    state = _state()
    update = audit_node(state)
    merge_update(state, update)
    old = snapshot_digest(state)

    state["fields"]["guarantee_amount"] = _field("guarantee_amount", "999999.00")
    state["docs"][0]["full_text"] += "\nedited"
    merge_update(state, gate_node(state, "start_approval", candidate_digest=old))

    assert state["gate"]["decision"] != "allowed"
    assert state["gate"]["candidate_content_sha256"] == snapshot_digest(state)


def test_a_failed_audit_leaves_no_old_findings_next_to_the_failed_stage():
    """rule-audit / Coverage + orchestration / 没检查必须可区分."""
    state = _state()
    del state["fields"]["guarantee_amount"]
    state["docs"][0]["full_text"] = state["docs"][0]["full_text"].replace("500000.00", "")
    state["docs"][0]["blocks"][0]["text"] = state["docs"][0]["full_text"]
    merge_update(state, audit_node(state))
    assert state["findings"], "the first audit must produce a finding"

    merge_update(state, audit_node(state, bundles=[]))  # deterministic failure: no bundle

    assert state["stages"][-1]["status"] == "failed"
    assert state["findings"] == []


def test_a_new_audit_clears_the_previous_gate_decision():
    """rule-audit / The gate answers one candidate; a new audit invalidates the old answer."""
    state = _state()
    merge_update(state, audit_node(state))
    merge_update(state, gate_node(state, "save_draft"))
    assert state["gate"]["decision"] == "allowed"

    state["fields"]["guarantee_amount"] = _field("guarantee_amount", "1.00")
    state["docs"][0]["full_text"] += "\nedited"
    merge_update(state, audit_node(state))

    assert state.get("gate") is None


def test_a_second_audit_does_not_accumulate_old_findings():
    """rule-audit / Every finding is bound to the snapshot it came from."""
    state = _state()
    del state["fields"]["guarantee_amount"]
    state["docs"][0]["full_text"] = state["docs"][0]["full_text"].replace("500000.00", "")
    state["docs"][0]["blocks"][0]["text"] = state["docs"][0]["full_text"]
    merge_update(state, audit_node(state))
    first = list(state["findings"])
    assert len(first) == 1

    state["fields"]["guarantee_number"] = _field("guarantee_number", "BG-2026-00417")
    state["docs"][0]["full_text"] += "\nedited"
    merge_update(state, audit_node(state))

    assert len(state["findings"]) == 1
    assert state["findings"][0]["id"] == "B-001"


def test_duplicate_results_for_one_planned_check_are_refused():
    """rule-audit / Every planned check receives exactly one state."""
    unit = Unit("SCHEMA:x:required", "schema", field_id="x", required=True)
    with pytest.raises(AuditReportError):
        summarise(
            [unit],
            [CheckResult(unit.check_id, PASS), CheckResult(unit.check_id, PASS)],
            snapshot_digest="d",
            schema_version="s",
            bundle_versions={},
        )


def test_a_crashing_rule_unit_does_not_take_the_audit_down(monkeypatch):
    """rule-audit / One checker crashes: the unit is failed, the rest still run."""

    def boom(*args, **kwargs):
        raise RuntimeError("injected rule crash")

    monkeypatch.setattr("app.audit.runner.evaluate_rule", boom)
    outcome = audit_state(_state(), snapshot_digest="d-1")

    assert outcome["report"]["counts"]["failed"] >= 1
    assert outcome["report"]["outcome"] != "no_findings"


def test_exporting_the_same_snapshot_twice_does_not_write_a_second_version(tmp_path):
    """orchestration / 重复提交: no duplicate version on replay."""
    store = DocVersionStore(tmp_path)
    state = _state(
        business_type="guarantee",
        verification={"verdict": "pass"},
        gate={"verdict": "pass", "candidate_content_sha256": "digest"},
    )
    first = export_node(state, versions=store)
    second = export_node(state, versions=store)

    assert first["export"]["version_no"] == 1
    assert second["export"] is None or second["export"]["version_no"] == 1
    assert len(list((tmp_path / "R-bug").glob("v*.json"))) == 1


def test_an_accepted_disposition_resolves_a_blocking_finding_for_export(monkeypatch):
    """rule-audit / disposition state + orchestration / 未处理项: handled means accepted."""
    def allowed(*args, **kwargs):
        return {
            "decision": "allowed",
            "operation": "formal_export",
            "candidate_content_sha256": "x",
            "policy_revision": "test",
            "evaluated_at": "2026-11-10T00:00:00+00:00",
            "reason_codes": [],
            "authorized_finding_ids": [],
        }

    monkeypatch.setattr("app.nodes.pipeline_gate.evaluate_operation", allowed)
    stages = [
        stage_report(stage, status="done", reason=None, agent=agent)
        for stage, agent in (
            ("ingest", "agent1"),
            ("parse", "agent1"),
            ("extract", "agent1"),
            ("normalize", "agent1"),
            ("agent2", "agent2"),
            ("agent3", "agent3"),
            ("audit", "agent4"),
        )
    ]
    state = {
        "run_id": "R-bug",
        "stages": stages,
        "fields": {},
        "legal": None,
        "verification": {"checks": [], "verdict": "pass", "credibility": {}, "score": None},
        "findings": [
            {"id": "B-001", "blocking": True, "resolved": False, "severity": "critical", "source": "business"}
        ],
        "dispositions": [{"finding_id": "B-001", "disposition": "accepted", "actor": "alice"}],
    }

    decision = evaluate_export_gate(state)
    assert decision["verdict"] == "pass"


# ---------------------------------------------------------------------------
# HTTP boundary / upload
# ---------------------------------------------------------------------------


def test_malformed_json_on_create_run_is_a_client_error(tmp_path):
    """console-api / refusals carry {code,message}; a malformed body is the client's error."""
    client = TestClient(
        create_app(store=None, llm=None, runs_dir=tmp_path / "runs"),
        raise_server_exceptions=False,
    )
    response = client.post(
        "/runs", content="{bad", headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_BODY"


def test_two_uploads_with_the_same_filename_keep_both_contents(tmp_path):
    """document-import / multiple files: each file keeps its own bytes and fingerprint."""
    client = TestClient(create_app(store=None, llm=None, runs_dir=tmp_path / "runs"))
    created = client.post(
        "/runs",
        files=[
            ("files", ("same.txt", b"first document", "text/plain")),
            ("files", ("same.txt", b"second document", "text/plain")),
        ],
    )
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]

    parsed = client.post(f"/runs/{thread_id}/stages/parse").json()

    assert {document["full_text"] for document in parsed["documents"]} == {
        "first document",
        "second document",
    }


@pytest.mark.parametrize(
    "finding",
    [
        {
            "id": "A-1",
            "severity": "critical",
            "gate_type": "advisory",
            "method": "deterministic",
            "target_operations": ["handoff"],
        },
        {
            "id": "A-2",
            "severity": "critical",
            "gate_type": "hard_block",
            "method": "semantic",
            "target_operations": ["start_approval"],
        },
        {
            "id": "A-3",
            "severity": "critical",
            "gate_type": "hard_block",
            "method": "deterministic",
            "target_operations": ["handoff"],
        },
    ],
)
def test_severity_or_another_operation_never_blocks_by_itself(finding):
    """rule-audit / Severity does not decide blocking + the gate answers per operation."""
    report = {
        "planned": 10,
        "counts": {"pass": 10, "finding": 0, "not_applicable": 0, "needs_input": 0,
                   "unable_to_assess": 0, "failed": 0},
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "current",
        "snapshot_digest": "d-1",
        "coverage": {"assessed": 10, "ratio": 1.0},
        "reasons": [],
    }
    from app.audit.gate import evaluate_gate

    decision = evaluate_gate(
        report, operation="start_approval", candidate_digest="d-1", findings=[finding]
    )
    assert decision["decision"] == "allowed"


def test_http_gate_rejects_a_replayed_old_candidate_digest(tmp_path):
    """rule-audit / The candidate is what gets checked: HTTP must not let a client re-point it."""
    from app.llm import resolve_llm
    from app.runs import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    client = TestClient(
        create_app(store=store, llm=resolve_llm("fixture:fixtures/llm/extract_sample.json"))
    )
    from pathlib import Path as _Path

    text = _Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")
    thread = client.post("/runs", json={"text": text}).json()["thread_id"]
    audited = client.post(f"/runs/{thread}/stages/audit").json()
    old = audited["verification"]["audit"]["snapshot_digest"]

    store.get(thread)["fields"]["guarantee_amount"]["value"] = "999999.00"
    answer = client.post(
        f"/runs/{thread}/gate",
        json={"operation": "start_approval", "candidate_digest": old},
    ).json()

    assert answer["gate"]["decision"] != "allowed"


def test_a_supported_claim_without_a_citation_is_a_finding():
    """rule-audit / citation_support: supported MUST carry a chunk id from this retrieval."""
    from app.audit.evidence import evaluate_evidence_unit

    unit = Unit("EVIDENCE:citation_support", "evidence")
    state = {
        "legal": {"claims": [{"text": "quoted text", "support": "supported", "chunk_id": None}]},
        "retrieved": [{"chunk_id": "chunk-1", "text": "quoted text"}],
    }
    result = evaluate_evidence_unit(unit, state)
    assert result.status != "pass"


def test_an_empty_coverage_declaration_is_not_a_pass():
    """rule-audit / coverage declaration: an empty block cannot mean 'fully covered'."""
    from app.audit.evidence import evaluate_evidence_unit

    unit = Unit("EVIDENCE:coverage_declaration", "evidence")
    state = {
        "legal": {"claims": [], "coverage": {}, "summary": "ok"},
        "retrieved": [{"chunk_id": "chunk-1", "text": "text"}],
    }
    result = evaluate_evidence_unit(unit, state)
    assert result.status != "pass"


def test_a_later_failed_stage_is_backfilled_even_if_it_succeeded_before():
    """orchestration / 阶段可独立触发 + latest-stage semantics: a later failure wins."""
    from app.standalone import plan_standalone

    state = {
        "stages": [
            {"stage": "parse", "status": "done"},
            {"stage": "extract", "status": "done"},
            {"stage": "extract", "status": "failed"},
            {"stage": "normalize", "status": "done"},
        ],
        "docs": [{"file_id": "F-1"}],
        "_candidates": [{"key": "guarantee_number"}],
        "fields": {"guarantee_number": {"value": "BG-1"}},
        "business_type": "guarantee",
        "files": [{"file_id": "F-1"}],
    }

    plan = plan_standalone("audit", state)
    assert "extract" in plan["backfill"]


def test_docx_table_cell_keeps_paragraph_boundaries(tmp_path):
    """agent-normalize / 解析必须保留原文结构: paragraph boundaries are layout facts, not noise."""
    import zipfile

    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:p><w:r><w:t>Alpha</w:t></w:r></w:p>
          <w:p><w:r><w:t>Beta</w:t></w:r></w:p>
        </w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    path = tmp_path / "cell.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)

    from app.parsing.parse import parse_file

    doc = parse_file(
        {
            "file_id": "F-1",
            "filename": "cell.docx",
            "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "path": str(path),
        }
    )

    text = doc["full_text"]
    assert "Alpha" in text and "Beta" in text
    assert "AlphaBeta" not in text


@pytest.mark.parametrize("values", [[0.7], [0.7, 0.7]])
def test_a_single_or_tied_candidate_keeps_a_positive_score(values):
    """regulatory-advice / 检索命中: a matched chunk must not disappear because it is the only hit."""
    from mercatoria.retrieve import _minmax

    normalised = _minmax(values)
    assert any(score > 0 for score in normalised), normalised


def test_all_files_failing_leaves_fields_empty_and_the_chain_not_done():
    """agent-normalize / 全部文件失败: fields empty, stage failed, never 7 placeholders."""
    from app.llm import resolve_llm
    from app.runtime import execute_chain

    state = {
        "run_id": "R-allfail",
        "files": [
            {
                "file_id": "F-1",
                "filename": "missing.pdf",
                "mime": "application/pdf",
                "path": "definitely-missing.pdf",
                "sha256": "a" * 64,
            }
        ],
        "findings": [],
        "trail": [],
        "stages": [],
    }
    execute_chain(
        state,
        ["parse", "extract", "normalize"],
        llm=resolve_llm("fixture:fixtures/llm/extract_sample.json"),
    )

    assert state["fields"] == {}
    assert all(report["status"] == "failed" for report in state["stages"])


def test_transport_validation_errors_use_the_error_envelope(tmp_path):
    """console-api / every refusal has {code,message,detail?}; 422/400 defaults are not that."""
    client = TestClient(create_app(store=None, llm=None, runs_dir=tmp_path / "runs"))

    invalid_bool = client.post("/runs?autostart=nope", json={"text": "x"})
    assert invalid_bool.status_code in (400, 422)
    assert "code" in invalid_bool.json() and "message" in invalid_bool.json()

    bad_multipart = client.post(
        "/runs",
        content="x",
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )
    assert bad_multipart.status_code in (400, 422)
    assert "code" in bad_multipart.json() and "message" in bad_multipart.json()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actor": 123, "reason": None},
        {"actor": "ops", "reason": 123},
    ],
)
def test_disposition_rejects_non_string_identity_and_reason(kwargs):
    """console-api / refusals: bad client types are 400 errors, never a 500."""
    from app.audit.disposition import DispositionError, append_event

    with pytest.raises(DispositionError):
        append_event(
            [],
            finding_id="B-001",
            disposition="rejected",
            severity="critical",
            **kwargs,
        )


def test_a_non_string_text_submission_is_rejected(tmp_path):
    """console-api / create run: `text` is a string; coercing a mapping silently corrupts it."""
    client = TestClient(create_app(store=None, llm=None, runs_dir=tmp_path / "runs"))

    response = client.post("/runs", json={"text": {"a": 1}})
    assert response.status_code == 400


def test_saving_a_draft_is_not_blocked_by_a_stale_audit_report():
    """rule-audit / Draft saving is not a content gate: identity/locking only."""
    from app.audit.gate import evaluate_gate
    from app.audit.policy import SAVE_DRAFT

    report = {
        "planned": 1,
        "counts": {"pass": 1, "finding": 0, "not_applicable": 0, "needs_input": 0,
                   "unable_to_assess": 0, "failed": 0},
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "stale",
        "snapshot_digest": "old",
        "coverage": {"assessed": 1, "ratio": 1.0},
        "reasons": [],
    }
    decision = evaluate_gate(report, operation=SAVE_DRAFT, candidate_digest="new")
    assert decision["decision"] == "allowed"


def test_a_disposition_cannot_resolve_a_different_finding_with_a_reused_id():
    """rule-audit / disposition is bound to a finding; ids must not be reused across snapshots."""
    from app.audit.gate import evaluate_gate

    state = {
        "findings": [{"id": "B-001", "severity": "critical", "source": "business"}],
        "dispositions": [
            {"finding_id": "B-001", "disposition": "accepted", "actor": "alice"}
        ],
    }
    # The graph applies reset's Overwrite([]) to this reducer key.
    state["findings"] = []
    assert state["findings"] == [], "reset clears the old findings"

    # A new audit produces a new B-001 (ids restart at 001) — it is a different finding.
    new_finding = {
        "id": "B-001",
        "severity": "critical",
        "gate_type": "human_review",
        "method": "deterministic",
        "target_operations": ["start_approval"],
    }
    report = {
        "planned": 1,
        "counts": {"pass": 1, "finding": 0, "not_applicable": 0, "needs_input": 0,
                   "unable_to_assess": 0, "failed": 0},
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "current",
        "snapshot_digest": "new-digest",
        "coverage": {"assessed": 1, "ratio": 1.0},
        "reasons": [],
    }
    decision = evaluate_gate(
        report,
        operation="start_approval",
        candidate_digest="new-digest",
        findings=[new_finding],
        dispositions=state["dispositions"],
    )
    assert decision["decision"] == "blocked"


def test_identical_content_reupload_has_an_independent_file_id_and_path(tmp_path):
    """document-import / 同名重传: independent file_id/path, identical sha256."""
    client = TestClient(create_app(store=None, llm=None, runs_dir=tmp_path / "runs"))
    created = client.post(
        "/runs",
        files=[
            ("files", ("same.txt", b"identical", "text/plain")),
            ("files", ("same.txt", b"identical", "text/plain")),
        ],
    )
    body = created.json()

    assert body["files"][0]["file_id"] != body["files"][1]["file_id"]
    assert body["files"][0]["path"] != body["files"][1]["path"]
    assert body["files"][0]["sha256"] == body["files"][1]["sha256"]


def test_a_scanned_pdf_that_went_through_ocr_is_labelled_image_ocr(tmp_path, monkeypatch):
    """document-import / OCR 的文本来源: OCR text MUST NOT appear as pdf_text."""
    fitz = pytest.importorskip("pymupdf")
    from tests.test_parse_import import _stub_ocr
    from app.parsing.parse import parse_file

    path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(str(path))
    document.close()
    _stub_ocr(monkeypatch, [(0.0, 0.0, 50.0, 10.0, "AMOUNT: USD 500,000.00\n", 0, 0)])

    doc = parse_file(
        {
            "file_id": "F-1",
            "filename": "scan.pdf",
            "mime": "application/pdf",
            "path": str(path),
        }
    )

    assert doc["full_text"]
    assert doc["form"] == "image_ocr"


def test_a_nested_docx_table_is_not_walked_twice(tmp_path):
    """document-import / DOCX 解析只取文本: blocks follow document order, without duplicates."""
    import zipfile

    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
  <w:tbl><w:tr><w:tc>
    <w:p><w:r><w:t>Outer</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Inner</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  </w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    path = tmp_path / "nested.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)

    from app.parsing.parse import parse_file

    doc = parse_file(
        {
            "file_id": "F-1",
            "filename": "nested.docx",
            "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "path": str(path),
        }
    )

    assert doc["full_text"].count("Inner") <= 1
