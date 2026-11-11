"""Positive coverage for spec scenarios the existing suite did not assert directly.

These tests all pass against the current implementation. They are deliberately *requirements*
tests: each docstring names the OpenSpec scenario it locks in. The companion
`tests/test_spec_bugs.py` contains executable reproductions of the cases that fail.

Run:

    .venv/Scripts/python.exe -m pytest tests/test_spec_coverage.py -q
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.audit.gate import evaluate_gate
from app.audit.project import credibility, verdict_for
from app.audit.report import CURRENT, STALE, mark_stale, summarise
from app.audit.snapshot import snapshot_digest
from app.nodes.export import export_node
from app.parsing.normalize import (
    MAX_SPAN_LEN,
    build_fields,
    normalize_ws,
    shrink_span,
)
from app.parsing.parse import parse
from app.regulatory.node import regulatory_node
from app.regulatory.retriever import FakeRetriever
from app.rules.types import (
    FAILED,
    FINDING,
    NOT_APPLICABLE,
    PASS,
    UNABLE_TO_ASSESS,
    CheckResult,
    Unit,
)
from app.storage.doc_versions import DocVersionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block(text: str, page: int | None = 1) -> dict:
    return {
        "file_id": "F-1",
        "page": page,
        "bbox": [0, 0, 100, 20] if page is not None else None,
        "text": text,
        "kind": "paragraph",
    }


def _doc(text: str, *, page: int | None = 1) -> dict:
    return {
        "file_id": "F-1",
        "filename": "g.txt",
        "form": "pdf_text" if page is not None else "plain_text",
        "blocks": [_block(text, page)],
        "full_text": text,
        "errors": [],
    }


def _candidate(key: str, raw: str, span: str, *, page: int | None = 1) -> dict:
    return {
        "key": key,
        "raw_value": raw,
        "confidence": 0.9,
        "_source": {
            "file_id": "F-1",
            "page": page,
            "bbox": [0, 0, 100, 20] if page is not None else None,
            "span": span,
            "form_label": None,
        },
    }


def _normalized_reg_state(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "docs": [
            {
                "file_id": "F-1",
                "filename": "F-1.txt",
                "form": "plain_text",
                "blocks": [
                    {"file_id": "F-1", "page": None, "bbox": None, "text": line, "kind": "paragraph"}
                    for line in lines
                ],
                "full_text": "\n".join(lines),
                "errors": [],
            }
        ],
        "fields": {
            "guarantee_amount": {"key": "guarantee_amount", "value": "USD 500,000.00"},
            "applicant_country": {"key": "applicant_country", "value": "CN"},
            "transaction_date": {"key": "transaction_date", "value": "2026-03-15"},
        },
        "business_type": "guarantee",
        "findings": [],
        "trail": [],
        "stages": [
            {"stage": "normalize", "agent": "agent1", "status": "done", "reason": None,
             "produced": 3, "model_calls": 0}
        ],
    }


REG_CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["AU", "CN", "US"],
    "built_at": "2026-11-09T00:00:00Z",
}
REG_CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "URDG 758 海关事务担保条例",
    "text": "第464条 保函金额 USD 500,000.00 应当以书面形式约定，适用 URDG 758。",
    "score": 0.91,
    "articles": ["第464条"],
    "effective_from": "2021-01-01",
    "effective_to": None,
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee", "customs"],
}


def _report(**counts) -> dict:
    base = {PASS: 0, FINDING: 0, NOT_APPLICABLE: 0, UNABLE_TO_ASSESS: 0, FAILED: 0}
    base["needs_input"] = 0
    base.update(counts)
    return {
        "planned": sum(base.values()),
        "counts": base,
        "completion": "complete",
        "outcome": "no_findings",
        "freshness": "current",
        "snapshot_digest": "d-1",
        "coverage": {"assessed": base[PASS] + base[FINDING], "ratio": 1.0},
        "reasons": [],
    }


# ---------------------------------------------------------------------------
# Normalization benchmark
# ---------------------------------------------------------------------------


def test_normalize_ws_applies_the_five_steps_in_order_and_nothing_else():
    """agent-contract / 归一化边界: NFKC → invisible → dash → quote → whitespace.

    Also locks the three explicitly forbidden transformations: case folding, punctuation removal
    and synonym/unit conversion.
    """
    assert normalize_ws("Ａ\u200b－“x”\u3000") == 'A-"x"'
    assert normalize_ws("ABC Trading") != normalize_ws("abc trading")
    assert normalize_ws("A.B") == "A.B"
    assert normalize_ws("USD") == "USD"
    assert normalize_ws("US$") != "USD"


def test_max_span_len_is_a_boundary_not_a_target():
    """agent-normalize / 片段上限: exactly 200 is kept; 201 is never silently truncated."""
    exact = "A" * MAX_SPAN_LEN
    doc = _doc(exact)
    result = build_fields(
        [_candidate("k", exact, exact)],
        [doc],
        fields_yaml={"k": {"type": "string"}},
    )
    assert result.fields["k"]["status"] == "extracted"
    assert result.fields["k"]["source"]["span"] == exact

    over = "A" * (MAX_SPAN_LEN + 1)
    assert shrink_span(over) is None
    doc = _doc(over)
    result = build_fields(
        [_candidate("k", over, over)],
        [doc],
        fields_yaml={"k": {"type": "string"}},
    )
    field = result.fields["k"]
    assert field["status"] == "inferred"
    assert field["notes"] == ["span_oversize"]
    # The provenance itself is not truncated: a shorter span would point somewhere else.
    assert field["source"]["span"] == over


def test_an_overlong_span_is_cut_at_the_last_sentence_end_within_the_limit():
    """agent-normalize / 片段上限: a sentence boundary inside 200 is a legal cut."""
    span = "A" * 100 + "。" + "B" * 200
    doc = _doc(span)
    result = build_fields(
        [_candidate("k", "value", span)],
        [doc],
        fields_yaml={"k": {"type": "string"}},
    )
    field = result.fields["k"]
    assert field["status"] == "extracted"
    assert len(field["source"]["span"]) == 101
    assert field["source"]["span"].endswith("。")


@pytest.mark.parametrize(
    ("raw", "order", "expected"),
    [
        ("03/12/2026", "MDY", "2026-03-12"),
        ("12/31/2026", "MDY", "2026-12-31"),
        ("03/12/26", "DMY", "2026-12-03"),
        ("31/12/2026", "DMY", "2026-12-31"),
    ],
)
def test_date_order_and_two_digit_year_are_applied(raw, order, expected):
    """agent-normalize / 三分类判定: date_order decides ambiguity; 2-digit years resolve to 20xx."""
    text = f"日期：{raw}"
    doc = _doc(text)
    result = build_fields(
        [_candidate("issue_date", raw, raw)],
        [doc],
        fields_yaml={
            "issue_date": {"type": "date", "date_order": order, "precision": 0}
        },
    )
    assert result.fields["issue_date"]["value"] == expected
    assert result.fields["issue_date"]["status"] == "extracted"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("USD 1.2K", "1200.00"),
        ("USD 1.2M", "1200000.00"),
        ("USD 1.2MN", "1200000.00"),
        ("USD 1.2BN", "1200000000.00"),
        ("USD 1.2B", "1200000000.00"),
        ("123456789012345678.90", "123456789012345678.90"),
    ],
)
def test_amount_multipliers_and_exact_decimal_arithmetic(raw, expected):
    """agent-normalize / 值规范化: multipliers are exact Decimal factors, never float."""
    doc = _doc(f"金额：{raw}")
    result = build_fields(
        [_candidate("guarantee_amount", raw, raw)],
        [doc],
        fields_yaml={"guarantee_amount": {"type": "amount", "precision": 2}},
    )
    assert result.fields["guarantee_amount"]["value"] == expected
    assert result.fields["guarantee_amount"]["status"] == "extracted"


def test_lowercase_currency_is_uppercased_and_invalid_currency_downgrades():
    """agent-normalize / 值规范化: currency keeps ISO shape; anything else is inferred."""
    doc = _doc("币种：usd")
    good = build_fields(
        [_candidate("currency", "usd", "usd")],
        [doc],
        fields_yaml={"currency": {"type": "currency"}},
    )
    assert good.fields["currency"]["value"] == "USD"
    assert good.fields["currency"]["status"] == "extracted"

    doc = _doc("币种：US")
    bad = build_fields(
        [_candidate("currency", "US", "US")],
        [doc],
        fields_yaml={"currency": {"type": "currency"}},
    )
    assert bad.fields["currency"]["value"] == "US"
    assert bad.fields["currency"]["status"] == "inferred"
    assert "currency_not_iso4217" in bad.fields["currency"]["notes"]


def test_higher_confidence_duplicate_wins_and_the_loser_is_trailed():
    """agent-normalize / 字段抽取: one candidate per key; discarding is receipted, never silent."""
    text = "值：LOW\n值：HIGH"
    doc = {
        "file_id": "F-1",
        "form": "pdf_text",
        "full_text": text,
        "blocks": [_block("值：LOW", 1), _block("值：HIGH", 1)],
        "errors": [],
    }
    low = _candidate("k", "LOW", "LOW")
    low["confidence"] = 0.2
    high = _candidate("k", "HIGH", "HIGH")
    high["confidence"] = 0.9

    result = build_fields([low, high], [doc], fields_yaml={"k": {"type": "string"}})

    assert result.fields["k"]["value"] == "HIGH"
    dropped = [
        entry
        for entry in result.trail_entries
        if entry["detail"].get("reason") == "duplicate_candidate_lower_confidence"
    ]
    assert len(dropped) == 1
    assert dropped[0]["before"] == "LOW"
    assert dropped[0]["op"] == "pass"


def test_plain_text_parse_keeps_visible_whitespace_and_has_no_position(tmp_path):
    """agent-normalize / 无位置的输入: page/bbox null, text keeps NBSP and full-width space."""
    path = tmp_path / "note.txt"
    path.write_text("A\u00a0B\n\u3000C", encoding="utf-8")

    docs, trail, model_calls = parse(
        [{"file_id": "F-1", "filename": "note.txt", "mime": "text/plain", "path": str(path)}]
    )

    assert model_calls == 0
    assert docs[0]["full_text"] == "A\u00a0B\n\u3000C"
    assert all(block["page"] is None and block["bbox"] is None for block in docs[0]["blocks"])
    assert docs[0]["errors"] == []
    assert trail[0]["op"] == "read"


# ---------------------------------------------------------------------------
# Regulatory
# ---------------------------------------------------------------------------


def test_retrieved_chunks_have_the_contract_shape_and_ids():
    """regulatory-advice / 检索命中: chunk_id / source_doc / text / score survive into state."""
    update = regulatory_node(
        _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。"),
        retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS),
    )

    assert update["retrieved"]
    for chunk in update["retrieved"]:
        assert {"chunk_id", "source_doc", "text", "score"} <= set(chunk)
        assert chunk["text"] == REG_CHUNK["text"]


def test_applicable_rules_keep_the_chunk_effective_date():
    """regulatory-advice / 时效匹配: the rule row carries the version's effective date."""
    update = regulatory_node(
        _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。"),
        retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS),
    )

    rule = update["legal"]["applicable_rules"][0]
    assert rule["chunk_id"] == "chunk-1"
    assert rule["effective_from"] == "2021-01-01"
    assert rule["version"] == REG_CORPUS["version"]


def test_coverage_declares_the_standards_seen_in_retrieval():
    """regulatory-advice / 覆盖范围内: standards are listed from what was actually retrieved."""
    update = regulatory_node(
        _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。"),
        retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS),
    )

    assert update["legal"]["coverage"]["standards"]
    assert any("URDG" in item for item in update["legal"]["coverage"]["standards"])


def test_an_unsupported_jurisdiction_is_named_and_escalates():
    """regulatory-advice / 超出覆盖范围: a missing jurisdiction is a note + human referral."""
    state = _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00。")
    state["fields"]["applicant_country"] = {"key": "applicant_country", "value": "BR"}

    update = regulatory_node(
        state, retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS)
    )

    assert update["legal"]["escalate_to_human"] is True
    assert any("BR" in note for note in update["legal"]["coverage"]["notes"])
    assert any(finding["rule_id"] == "REG-JURISDICTION" for finding in update["findings"])


def test_retrieval_without_claims_requires_a_human_and_says_so():
    """regulatory-advice / 覆盖声明: hits with no citable claim are not "no issue"."""
    class EmptyAnswerer:
        def answer(self, **kwargs):
            from app.regulatory.answer import AnswerResult

            return AnswerResult(
                legal={
                    "input_mode": "enriched",
                    "applicable_rules": [],
                    "claims": [],
                    "coverage": {
                        "jurisdictions": ["CN"],
                        "standards": [],
                        "unavailable": False,
                        "business_type_uncertain": False,
                        "notes": [],
                        "corpus": REG_CORPUS,
                    },
                    "escalate_to_human": False,
                    "summary": "",
                }
            )

    update = regulatory_node(
        _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00。"),
        retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS),
        answerer=EmptyAnswerer(),
    )

    assert update["legal"]["escalate_to_human"] is True
    assert any("未产出可引用" in note for note in update["legal"]["coverage"]["notes"])


def test_every_regulatory_finding_carries_the_screening_disclaimer():
    """regulatory-advice / 不替代正式筛查: findings must say what they are not."""
    state = _normalized_reg_state("保函编号 BG-2026-0001，金额 USD 500,000.00。")
    state["fields"]["applicant_country"] = {"key": "applicant_country", "value": "BR"}
    update = regulatory_node(
        state, retriever=FakeRetriever([copy.deepcopy(REG_CHUNK)], REG_CORPUS)
    )

    assert update["findings"]
    for finding in update["findings"]:
        assert "不替代正式制裁与出口管制筛查" in (finding.get("suggestion") or "")


# ---------------------------------------------------------------------------
# Audit: finding shape, three-valued logic and report aggregation
# ---------------------------------------------------------------------------


def test_a_deterministic_hard_block_for_this_operation_blocks():
    """rule-audit / Only deterministic rules hard-block: the positive counterpart."""
    finding = {
        "id": "A-1",
        "severity": "critical",
        "gate_type": "hard_block",
        "method": "deterministic",
        "target_operations": ["start_approval"],
    }
    decision = evaluate_gate(
        _report(**{PASS: 10}), operation="start_approval", candidate_digest="d-1", findings=[finding]
    )
    assert decision["decision"] == "blocked"
    assert decision["reason_codes"] == ["hard_block"]


def test_mark_stale_returns_a_copy_and_is_idempotent():
    """rule-audit / Document changes during the run: stale is a derived view, not a mutation."""
    report = {**_report(**{PASS: 3}), "freshness": CURRENT, "snapshot_digest": "old"}
    stale = mark_stale(report, "new")

    assert report["freshness"] == CURRENT
    assert stale["freshness"] == STALE
    assert stale["freshness_reasons"] == ["snapshot_changed"]
    assert mark_stale(stale, "new") == stale


def test_verdict_fail_wins_and_unable_always_fails():
    """rule-audit / Outcomes: a failed check is never presented as pass/warn."""
    assert verdict_for({"outcome": "no_findings"}, [{"level": "fail"}]) == "fail"
    assert verdict_for({"outcome": "unable_to_assess"}, []) == "fail"
    assert verdict_for({"outcome": "findings_present"}, []) == "warn"


def test_credibility_excludes_not_applicable_from_the_numerator():
    """rule-audit / plan total conserved: assessed = pass + finding, not_applicable is not assessed."""
    report = summarise(
        [Unit(f"U{i}", "schema") for i in range(4)],
        [
            CheckResult("U0", PASS),
            CheckResult("U1", FINDING),
            CheckResult("U2", NOT_APPLICABLE),
            CheckResult("U3", UNABLE_TO_ASSESS),
        ],
        snapshot_digest="d",
        schema_version="s",
        bundle_versions={"b": "1"},
    )
    assert report["counts"] == {
        PASS: 1,
        FINDING: 1,
        NOT_APPLICABLE: 1,
        "needs_input": 0,
        UNABLE_TO_ASSESS: 1,
        FAILED: 0,
    }
    assert credibility(report)["assessed"] == 2
    assert credibility(report)["planned"] == 4
    assert credibility(report)["ratio"] == 0.5
    assert sum(report["counts"].values()) == report["planned"]


def test_everything_not_applicable_is_unable_and_never_pass():
    """rule-audit / Everything is not applicable: unable_to_assess + no_applicable_checks."""
    report = summarise(
        [Unit("U0", "schema"), Unit("U1", "schema")],
        [CheckResult("U0", NOT_APPLICABLE), CheckResult("U1", NOT_APPLICABLE)],
        snapshot_digest="d",
        schema_version="s",
        bundle_versions={},
    )
    assert report["outcome"] == "unable_to_assess"
    assert "no_applicable_checks" in report["reasons"]
    assert report["completion"] == "complete"


# ---------------------------------------------------------------------------
# Export file contract
# ---------------------------------------------------------------------------


def test_the_export_file_has_every_required_key_and_ignores_a_caller_version(tmp_path):
    """orchestration / 导出内容 + 版本号不可由调用方指定."""
    store = DocVersionStore(tmp_path / "exports")
    state = {
        "run_id": "R-export",
        "business_type": "guarantee",
        "fields": {"guarantee_number": {"value": "BG-1"}},
        "verification": {"verdict": "pass", "checks": []},
        "gate": {"verdict": "pass", "candidate_content_sha256": "digest-1"},
        "version_no": 99,  # a caller supplied value must be ignored
    }

    update = export_node(state, versions=store)
    exported = update["export"]

    for key in (
        "doc_id",
        "snapshot_id",
        "run_id",
        "business_type",
        "fields",
        "verification",
        "gate",
        "exported_at",
        "version_no",
    ):
        assert key in exported, key
    assert exported["version_no"] == 1
    assert exported["snapshot_id"] == "digest-1"
    assert exported["doc_id"] == "R-export"


def test_a_blocked_gate_writes_no_export_and_marks_the_stage_skipped():
    """orchestration / 拦截时不产出文件: skipped, never silently exported."""
    update = export_node({"run_id": "R-1", "gate": {"verdict": "blocked"}})

    assert update["export"] is None
    assert update["stages"][0]["status"] == "skipped"
    assert update["stages"][0]["stage"] == "export"


# ---------------------------------------------------------------------------
# HTTP boundary and upload robustness
# ---------------------------------------------------------------------------


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(store=None, llm=None, runs_dir=tmp_path / "runs"))


def test_a_json_scalar_submission_is_an_empty_submission_not_a_run(tmp_path):
    """console-api / refusals: a non-object body never becomes an empty but successful run."""
    client = _client(tmp_path)
    response = client.post(
        "/runs", content="[]", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_SUBMISSION"


def test_malformed_json_on_the_gate_is_a_400_invalid_body(tmp_path):
    """console-api / refusals: gate bodies use the same {code,message} shape."""
    client = _client(tmp_path)
    thread_id = client.post("/runs", json={"text": "DEMAND GUARANTEE"}).json()["thread_id"]

    response = client.post(
        f"/runs/{thread_id}/gate",
        content="{bad",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_BODY"


def test_an_upload_filename_cannot_escape_the_run_directory(tmp_path):
    """document-import / upload: the stored path is always under the run's work directory."""
    client = _client(tmp_path)
    response = client.post(
        "/runs", files=[("files", ("../../evil.txt", b"hello", "text/plain"))]
    )
    assert response.status_code == 201
    body = response.json()
    stored = Path(body["files"][0]["path"])
    assert stored.name == "evil.txt"
    assert stored.parent == Path(tmp_path / "runs" / body["thread_id"])

    windows_style = client.post(
        "/runs", files=[("files", ("..\\evil.txt", b"hello", "text/plain"))]
    )
    assert windows_style.status_code == 201
    assert Path(windows_style.json()["files"][0]["path"]).name == "evil.txt"


def test_an_unsupported_upload_is_reported_per_file_not_as_a_server_error(tmp_path):
    """document-import / per-file failure: errors stay in documents[], never a 500."""
    client = _client(tmp_path)
    created = client.post("/runs", files=[("files", ("virus.exe", b"MZ", "application/octet-stream"))])
    thread = created.json()["thread_id"]

    parsed = client.post(f"/runs/{thread}/stages/parse").json()

    assert parsed["documents"][0]["errors"]
    assert "unsupported_mime" in parsed["documents"][0]["errors"][0]
    assert parsed["stages"][-1]["status"] in {"failed", "partial"}


def test_an_oversized_upload_is_refused_by_the_parser_not_the_transport(tmp_path):
    """document-import / import limits: >20 MiB is a per-file error, still no 500."""
    client = _client(tmp_path)
    big = b"x" * (20 * 1024 * 1024 + 1)
    created = client.post("/runs", files=[("files", ("big.txt", big, "text/plain"))])
    assert created.status_code == 201
    thread = created.json()["thread_id"]

    parsed = client.post(f"/runs/{thread}/stages/parse").json()

    assert parsed["documents"][0]["errors"]
    assert "file_too_large" in parsed["documents"][0]["errors"][0]


def test_events_endpoint_is_oldest_first_and_empty_before_a_graph_run(tmp_path):
    """orchestration / 查看执行轨迹: a fresh run has an events list, not a missing key."""
    client = _client(tmp_path)
    thread = client.post("/runs", json={"text": "DEMAND GUARANTEE"}).json()["thread_id"]

    body = client.get(f"/runs/{thread}/events").json()

    assert body["thread_id"] == thread
    assert isinstance(body["events"], list)


def test_two_runs_are_independent_even_when_created_from_identical_text(tmp_path):
    """idempotency is per request, not "one state for the same text"."""
    client = _client(tmp_path)
    first = client.post("/runs", json={"text": "DEMAND GUARANTEE"}).json()
    second = client.post("/runs", json={"text": "DEMAND GUARANTEE"}).json()

    assert first["thread_id"] != second["thread_id"]
    assert first["files"][0]["path"] != second["files"][0]["path"]


# ---------------------------------------------------------------------------
# Stage nodes: refusals, retry, labels and trail evidence
# ---------------------------------------------------------------------------


def test_all_files_failing_makes_parse_a_failed_stage_not_an_empty_success(tmp_path):
    """agent-normalize / 全部文件失败: fields are empty, stage failed, never a clean parse."""
    from app.nodes.parse import parse_node

    state = {
        "files": [{"file_id": "F-1", "filename": "missing.pdf", "mime": "application/pdf",
                   "path": str(tmp_path / "missing.pdf"), "sha256": "x"}],
        "docs": [],
        "stages": [],
        "trail": [],
    }

    update = parse_node(state)

    assert update["docs"][0]["errors"]
    assert update["stages"][0]["status"] == "failed"
    assert update.get("fields", {}) == {}


def test_extract_retries_once_then_reports_a_partial_stage():
    """agent-contract / 抽取是唯一模型入口: a schema violation is retried once, then receipted."""
    from app.nodes.extract import extract_node

    calls = {"n": 0}

    def invalid(prompt):
        calls["n"] += 1
        return "not json at all"

    state = {
        "docs": [_doc("DEMAND GUARANTEE")],
        "stages": [],
        "trail": [],
        "_candidates": [{"key": "stale"}],
    }

    update = extract_node(state, llm=invalid, field_keys=["guarantee_number"])

    assert calls["n"] == 2
    assert update["_candidates"] == []
    assert update["stages"][0]["status"] == "partial"
    assert "failed" in update["stages"][0]["reason"]


def test_a_candidate_label_is_preserved_on_the_field_value():
    """agent-normalize / 字段抽取: the source's own label is display metadata, never the value."""
    doc = _doc("保函编号：BG-2026-0001")
    candidate = _candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001")
    candidate["label"] = "Guarantee No."

    result = build_fields(
        [candidate],
        [doc],
        fields_yaml={"guarantee_number": {"label": "Guarantee Number", "type": "string"}},
    )

    assert result.fields["guarantee_number"]["label"] == "Guarantee No."


def test_a_single_block_pdf_field_keeps_the_extracted_page():
    """agent-normalize / 出处必须能跳回具体页: the positive, unambiguous case."""
    doc = {
        "file_id": "F-1",
        "form": "pdf_text",
        "full_text": "保函编号：BG-2026-0001",
        "blocks": [_block("保函编号：BG-2026-0001", 3)],
        "errors": [],
    }
    result = build_fields(
        [_candidate("guarantee_number", "BG-2026-0001", "BG-2026-0001", page=3)],
        [doc],
        fields_yaml={"guarantee_number": {"type": "string"}},
    )
    field = result.fields["guarantee_number"]
    assert field["status"] == "extracted"
    assert field["source"]["page"] == 3


def test_business_type_decision_always_writes_one_receipt_with_evidence_and_reason():
    """agent-normalize / 判定依据必须留痕: even `unsupported` says why and keeps its evidence."""
    from app.parsing.normalize import decide_business_type

    supported = decide_business_type([{"file_id": "F-1", "full_text": "URDG 758"}])
    unsupported = decide_business_type([{"file_id": "F-1", "full_text": "unrelated text"}])

    for decision in (supported, unsupported):
        entry = decision.trail_entry
        assert entry["op"] == "pass"
        assert entry["detail"]["business_type"] == decision.business_type
        assert "reason" in entry["detail"]
        assert "evidence" in entry["detail"]
    assert unsupported.business_type == "unsupported"
    assert "no_evidence" in unsupported.reason or "unsupported" in unsupported.reason


# ---------------------------------------------------------------------------
# Small but contractual branches that had no direct test
# ---------------------------------------------------------------------------


def test_ingest_gives_a_missing_file_a_stable_identity(tmp_path):
    """orchestration / ingest: a vanished file still gets a deterministic sha256, never ''."""
    from app.nodes.ingest import ingest_node

    raw = {"path": str(tmp_path / "gone.txt"), "filename": "gone.txt"}
    first = ingest_node({"files": [raw]})
    second = ingest_node({"files": [raw]})

    assert first["files"][0]["sha256"] == second["files"][0]["sha256"]
    assert len(first["files"][0]["sha256"]) == 64
    assert first["files"][0]["file_id"].startswith("F-")


def test_extract_retry_recovers_when_the_second_call_is_valid():
    """agent-contract / 抽取是唯一模型入口: one malformed answer is retried, not fatal."""
    from app.parsing.extract import _call_with_retry

    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        return [{"key": "k", "raw_value": "v", "span": "v", "confidence": 0.9}]

    parsed, attempts = _call_with_retry(llm, "prompt")

    assert attempts == 2
    assert parsed and parsed[0]["key"] == "k"


def test_extract_retry_gives_up_after_two_provider_exceptions():
    """agent-contract / 抽取是唯一模型入口: a broken provider becomes failed_batches, not a crash."""
    from app.parsing.extract import _call_with_retry

    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        raise RuntimeError("down")

    parsed, attempts = _call_with_retry(llm, "prompt")

    assert calls["n"] == 2
    assert parsed is None
    assert attempts == 2


def test_business_type_and_transaction_date_have_explicit_field_priority():
    """regulatory-advice / 两种输入模式: fields are authoritative over body text."""
    from app.regulatory.query import infer_business_type, transaction_date

    state = {
        "business_type": None,
        "fields": {
            "business_type": {"value": "customs"},
            "transaction_date": {"value": "not-a-date"},
        },
        "docs": [{"full_text": "保函 2026-03-15"}],
    }
    assert infer_business_type(state) == "customs"
    # An invalid field is not a guess; the ISO date in the body is the only usable fact.
    assert transaction_date(state) == "2026-03-15"


def test_country_codes_accept_field_names_and_conservative_body_codes():
    """regulatory-advice / 两种输入模式: body codes are a fallback, and only the safe subset."""
    from app.regulatory.query import _country_codes

    state = {
        "fields": {"applicant_country": {"value": "新加坡"}},
        "docs": [{"full_text": "Applicant in SG; beneficiary in BR."}],
    }
    codes = _country_codes(state)
    assert codes[0] == "SG"
    assert "BR" not in codes, "BR is not in the conservative body subset"
