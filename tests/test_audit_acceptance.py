"""Tasks 9.1-9.3 — acceptance over the pure engine (no transport needed)."""

from __future__ import annotations

from app.audit.gate import evaluate_gate
from app.audit.policy import ALLOWED, BLOCKED, INDETERMINATE, START_APPROVAL, SUBMIT_VERSION
from app.audit.report import OUTCOME_FINDINGS, OUTCOME_NEEDS_INPUT, OUTCOME_NONE, STALE
from app.audit.runner import audit_state
from app.rules.types import FINDING, NEEDS_INPUT, NOT_APPLICABLE, PASS

DOC_VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Beta Construction Ltd",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}
DOC_TEXT = "Guarantee\n" + "\n".join(f"{key}: {value}" for key, value in DOC_VALUES.items())


def _field(key: str, value: str, *, status: str = "extracted") -> dict:
    source = (
        {"file_id": "F-1", "page": 1, "bbox": None, "span": value, "form_label": None}
        if status == "extracted"
        else None
    )
    return {
        "key": key,
        "value": value,
        "status": status,
        "confirmed": False,
        "edited_by_user": False,
        "source": source,
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _state(*, statuses: dict | None = None, omit: tuple[str, ...] = ()) -> dict:
    statuses = statuses or {}
    fields = {
        key: _field(key, value, status=statuses.get(key, "extracted"))
        for key, value in DOC_VALUES.items()
        if key not in omit
    }
    return {
        "docs": [{"file_id": "F-1", "full_text": DOC_TEXT}],
        "fields": fields,
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }


def _audit(state: dict, *, snapshot_digest: str = "digest-1", current_digest: str | None = None) -> dict:
    return audit_state(state, snapshot_digest=snapshot_digest, current_digest=current_digest)


def _gate(report: dict, findings: list[dict], operation: str = START_APPROVAL, digest: str = "digest-1"):
    return evaluate_gate(report, operation=operation, candidate_digest=digest, findings=findings)


def test_at01_determinism():
    """9.1 — same snapshot, same bundle, same engine ⇒ identical report."""
    first = _audit(_state())
    second = _audit(_state())

    assert first["report"] == second["report"]
    assert [result.status for result in first["results"]] == [r.status for r in second["results"]]
    assert first["conflicts"] == second["conflicts"] == []


def test_clean_document_has_no_findings_and_can_start_approval():
    """9.2 — the clean case is `no_findings`, and only then is approval allowed."""
    result = _audit(_state())

    assert result["report"]["outcome"] == OUTCOME_NONE
    assert result["report"]["completion"] == "complete"
    assert result["findings"] == []
    assert result["report"]["counts"][PASS] > 0
    assert _gate(result["report"], result["findings"])["decision"] == ALLOWED


def test_missing_required_field_is_a_finding_and_blocks_approval():
    """9.2 / AT-02 — absence is reported, not skipped."""
    result = _audit(_state(omit=("guarantee_amount",)))
    report = result["report"]

    assert report["outcome"] == OUTCOME_FINDINGS
    required = [
        finding
        for finding in result["findings"]
        if finding["rule_ref"]["rule_id"] == "SCHEMA:guarantee_amount:required"
    ]
    assert required, "the missing required field must produce a finding"
    assert required[0]["gate_type"] == "hard_block"

    decision = _gate(report, result["findings"])
    assert decision["decision"] == BLOCKED
    assert decision["reason_codes"] == ["hard_block"]


def test_unconfirmed_values_need_input_and_block_approval_but_not_submission():
    """9.2 — inferred values are never silently treated as confirmed."""
    result = _audit(_state(statuses={key: "inferred" for key in DOC_VALUES}))
    report = result["report"]

    assert report["outcome"] == OUTCOME_NEEDS_INPUT
    assert report["counts"][NEEDS_INPUT] > 0
    assert report["counts"][FINDING] == 0
    assert any(item.status == NOT_APPLICABLE for item in result["results"])

    approval = _gate(report, result["findings"])
    submission = _gate(report, result["findings"], operation=SUBMIT_VERSION)

    assert approval["decision"] == BLOCKED
    assert approval["reason_codes"] == ["needs_input"]
    assert submission["decision"] == ALLOWED
    assert "gaps_listed" in submission["reason_codes"]


def test_at17_a_changed_document_cannot_reuse_the_report():
    """9.3 — a stale report never allows a protected operation."""
    result = _audit(_state(), snapshot_digest="digest-1")
    assert result["report"]["freshness"] != STALE

    stale = _gate(result["report"], result["findings"], digest="digest-2")
    assert stale["decision"] == INDETERMINATE
    assert stale["reason_codes"] == ["stale_report"]

    marked = _audit(_state(), snapshot_digest="digest-1", current_digest="digest-2")
    assert marked["report"]["freshness"] == STALE
    assert marked["report"]["freshness_reasons"] == ["snapshot_changed"]
    assert marked["report"]["snapshot_digest"] == "digest-1"


def test_conflicting_rule_versions_block_approval(tmp_path):
    """Two published versions of one rule: the report cannot claim a verdict and the gate refuses."""
    import yaml

    from app.rules.bundles import load_bundle

    def publish(name: str, rule_version: int):
        path = tmp_path / f"{name}.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "bundle_id": name,
                    "version": "1.0.0",
                    "published": True,
                    "rules": [
                        {
                            "rule_id": "GR-AMOUNT-POSITIVE",
                            "version": rule_version,
                            "title": "amount positive",
                            "severity": "critical",
                            "gate_type": "hard_block",
                            "target_operations": [START_APPROVAL],
                            "expression": {"op": "exists", "field_id": "guarantee_amount"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return load_bundle(path)

    bundles = [publish("bank", 1), publish("client", 2)]
    result = audit_state(_state(), bundles=bundles, snapshot_digest="digest-1")

    assert "rule_conflict" in result["report"]["reasons"]
    assert result["report"]["outcome"] != OUTCOME_NONE

    decision = evaluate_gate(
        result["report"],
        operation=START_APPROVAL,
        candidate_digest="digest-1",
        findings=result["findings"],
    )
    assert decision["decision"] == BLOCKED
    assert decision["reason_codes"] == ["rule_conflict"]


def test_evidence_family_runs_inside_the_audit():
    state = _state()
    state["trail"] = [{"id": "agent1.normalize#009", "op": "rewrite"}]

    result = _audit(state)
    evidence_findings = [finding for finding in result["findings"] if finding["category"] == "evidence"]

    assert evidence_findings, "an overreach operation must surface as a finding"
    assert evidence_findings[0]["rule_ref"]["rule_id"] == "EVIDENCE:trail_overreach"