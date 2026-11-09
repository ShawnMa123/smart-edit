"""Evidence family (design D1): the values the audit reasons about must be traceable.

These checks used to be the whole group. They stay because an audit that judges a number nobody can
locate in the source is worthless — but they now guard the audit's *own* inputs rather than being its
identity.
"""

from __future__ import annotations

from app.parsing.normalize import normalized_full_texts, span_locatable
from app.regulatory.entities import extract_entities
from app.rules.types import (
    FAILED,
    FINDING,
    NOT_APPLICABLE,
    PASS,
    CheckResult,
    RuleEvaluationError,
    Unit,
)
from app.state import OVERREACH_OPS

REGULATORY_REASON = "requires_agent_regulatory_output"
VERIFY_REASON = "requires_agent_verify_output"
# Checks with no implementation yet report the missing upstream capability, never `pass`.
NOT_RUN_REASON = REGULATORY_REASON
_UNAVAILABLE_REASONS = {"conclusion_conflict": VERIFY_REASON}


def _finding(unit: Unit, title: str, severity: str, gate_type: str, detail: dict) -> dict:
    return {
        "rule_ref": {"rule_id": unit.check_id, "version": 1},
        "title": title,
        "severity": severity,
        "gate_type": gate_type,
        "target_operations": ["start_approval", "formal_export", "handoff"] if gate_type == "hard_block" else [],
        "category": "evidence",
        "field_id": detail.get("field_id"),
        "evidence": detail.get("evidence"),
        "detail": detail,
    }


def _check_trail_overreach(unit: Unit, state: dict) -> CheckResult:
    entries = [entry for entry in state.get("trail") or [] if entry.get("op") in OVERREACH_OPS]
    if not entries:
        return CheckResult(unit.check_id, PASS)
    detail = {"entry_ids": [entry.get("id") for entry in entries], "evidence": entries[0].get("op")}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "Source text was summarised, rewritten or dropped", "critical", "hard_block", detail),
    )


def _check_provenance(unit: Unit, state: dict) -> CheckResult:
    fields = state.get("fields") or {}
    extracted = {key: value for key, value in fields.items() if value.get("status") == "extracted"}
    if not extracted:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_extracted_values")

    # Normalise each document once, not once per field (design D12).
    normalized = normalized_full_texts(state.get("docs") or [])
    broken = []
    for key, value in extracted.items():
        source = value.get("source")
        if not source or not span_locatable(source, [], normalized=normalized):
            broken.append(key)
    if not broken:
        return CheckResult(unit.check_id, PASS)

    detail = {"field_ids": broken, "evidence": ", ".join(broken)}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "An extracted value cannot be located in its own file", "critical", "hard_block", detail),
    )


def _check_finding_anchor(unit: Unit, state: dict) -> CheckResult:
    findings = state.get("findings") or []
    if not findings:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_findings")

    known = set((state.get("fields") or {})) | set((state.get("extra_fields") or {}))
    dangling = [
        finding.get("id")
        for finding in findings
        if any(key not in known for key in (finding.get("field_keys") or []))
    ]
    if not dangling:
        return CheckResult(unit.check_id, PASS)

    detail = {"finding_ids": dangling, "evidence": ", ".join(str(item) for item in dangling)}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "A finding points at a field that does not exist", "warn", "advisory", detail),
    )


_UNCOVERED_MARKERS = (
    "未覆盖",
    "未涵盖",
    "not covered",
    "coverage unavailable",
    "法规建议未覆盖",
)
_UNCERTAIN_MARKERS = ("业务类型不确定", "business type uncertain")


def _check_citation_support(unit: Unit, state: dict) -> CheckResult:
    legal = state.get("legal") or {}
    claims = legal.get("claims") or []
    if not legal or not claims:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_regulatory_claims")

    chunks = {
        str(chunk.get("chunk_id")): chunk
        for chunk in state.get("retrieved") or []
        if chunk.get("chunk_id")
    }
    fabricated: list[str] = []
    entity_gaps: list[dict] = []
    inconsistent: list[str] = []

    for claim in claims:
        chunk_id = claim.get("chunk_id")
        if not chunk_id:
            continue
        key = str(chunk_id)
        chunk = chunks.get(key)
        if chunk is None:
            fabricated.append(key)
        else:
            # Agent 3's extractor returns the matched source text, so ask the honest question:
            # does that fact appear verbatim in the cited chunk? (The check stays independent of
            # `cite_check`; only the extraction pattern set is shared.)
            text = " ".join(str(chunk.get("text") or "").split())
            missing = [
                entity
                for entity in extract_entities(str(claim.get("text") or ""))
                if " ".join(entity.split()) not in text
            ]
            if missing:
                entity_gaps.append(
                    {
                        "chunk_id": key,
                        "claim": claim.get("text"),
                        "missing_entities": sorted(missing),
                    }
                )
        if claim.get("support") == "insufficient":
            inconsistent.append(key)

    if fabricated or entity_gaps:
        detail = {
            "chunk_ids": fabricated,
            "entity_gaps": entity_gaps,
            "evidence": (fabricated or [gap["chunk_id"] for gap in entity_gaps])[0],
        }
        return CheckResult(
            unit.check_id,
            FINDING,
            finding=_finding(
                unit,
                "A regulatory claim cites a chunk that does not support it",
                "critical",
                "hard_block",
                detail,
            ),
        )

    if inconsistent:
        detail = {"chunk_ids": inconsistent, "evidence": inconsistent[0]}
        return CheckResult(
            unit.check_id,
            FINDING,
            finding=_finding(
                unit,
                "A claim marked insufficient still cites a chunk",
                "warn",
                "advisory",
                detail,
            ),
        )

    return CheckResult(unit.check_id, PASS)


def _coverage_text(legal: dict) -> str:
    coverage = legal.get("coverage") or {}
    notes = coverage.get("notes")
    if isinstance(notes, str):
        notes = [notes]
    return " ".join([str(legal.get("summary") or ""), *(str(note) for note in notes or [])]).lower()


def _check_coverage_declaration(unit: Unit, state: dict) -> CheckResult:
    legal = state.get("legal") or {}
    if not legal:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_regulatory_output")

    coverage = legal.get("coverage") or {}
    retrieved = state.get("retrieved") or []
    unavailable = coverage.get("unavailable") is True
    summary = str(legal.get("summary") or "").lower()

    if unavailable and not any(marker in summary for marker in _UNCOVERED_MARKERS):
        detail = {"unavailable": True, "summary": legal.get("summary"), "evidence": "unavailable"}
        return CheckResult(
            unit.check_id,
            FINDING,
            finding=_finding(
                unit,
                "The regulatory answer says coverage is unavailable without declaring the gap",
                "critical",
                "hard_block",
                detail,
            ),
        )

    if not unavailable and not retrieved:
        detail = {"unavailable": False, "retrieved": 0, "evidence": "no_retrieval"}
        return CheckResult(
            unit.check_id,
            FINDING,
            finding=_finding(
                unit,
                "Coverage is claimed but nothing was retrieved",
                "critical",
                "hard_block",
                detail,
            ),
        )

    text = _coverage_text(legal)
    if coverage.get("business_type_uncertain") is True and not any(
        marker in text for marker in _UNCERTAIN_MARKERS
    ):
        detail = {"business_type_uncertain": True, "evidence": "business_type_uncertain"}
        return CheckResult(
            unit.check_id,
            FINDING,
            finding=_finding(
                unit,
                "The business type is uncertain but the answer does not say so",
                "warn",
                "advisory",
                detail,
            ),
        )

    return CheckResult(unit.check_id, PASS)


_CHECKS = {
    "trail_overreach": _check_trail_overreach,
    "provenance": _check_provenance,
    "finding_anchor": _check_finding_anchor,
    "citation_support": _check_citation_support,
    "coverage_declaration": _check_coverage_declaration,
}


def evaluate_evidence_unit(unit: Unit, state: dict) -> CheckResult:
    """Evaluate one evidence unit. Checks this build cannot run are `not_applicable` with a reason."""
    name = unit.check_id.split(":", 1)[-1]
    check = _CHECKS.get(name)
    if check is None:
        reason = _UNAVAILABLE_REASONS.get(name, NOT_RUN_REASON)
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code=reason)
    try:
        return check(unit, state)
    except RuleEvaluationError as exc:
        return CheckResult(unit.check_id, FAILED, reason_code=str(exc))
    except Exception as exc:  # a crashing checker must not take the audit down
        return CheckResult(unit.check_id, FAILED, reason_code=f"checker_crashed: {type(exc).__name__}")


def evaluate_all(units: list[Unit], state: dict) -> list[CheckResult]:
    """Evaluate every evidence unit, isolating failures (task 8.3)."""
    return [evaluate_evidence_unit(unit, state) for unit in units]