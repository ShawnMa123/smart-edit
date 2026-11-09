"""`merge` node: one deterministic ordering of the two parallel branches' findings.

Contract: `openspec/changes/poc-skeleton/design.md` §9.

Merge **sorts and de-duplicates**; it never renumbers (`N-` / `B-` / `R-` ids are allocated by
their producer and are the only stable handle a reviewer has). The de-duplication key is the
contract key `(source, rule_id, sorted(field_keys), evidence)`, so two agents reporting the same
problem do not become two problems, and different sources stay distinct.
"""

from __future__ import annotations

try:  # LangGraph 1.x
    from langgraph.types import Overwrite
except ImportError:  # pragma: no cover
    from langgraph.graph.message import Overwrite  # type: ignore[no-redef]

from app.stages import stage_report
from app.state import FINDING_PREFIX

MERGE_STAGE = "merge"
_SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}


def _dedupe_key(finding: dict) -> tuple:
    return (
        finding.get("source"),
        finding.get("rule_id"),
        tuple(sorted(finding.get("field_keys") or [])),
        finding.get("evidence"),
    )


def merge_findings(findings: list[dict]) -> list[dict]:
    """Stable order: severity → blocking → id. Duplicate keys keep their first occurrence."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for finding in findings:
        source = str(finding.get("source") or "")
        expected = FINDING_PREFIX.get(source)
        finding_id = str(finding.get("id") or "")
        if expected is None or not finding_id.startswith(f"{expected}-"):
            raise ValueError(
                f"finding {finding_id!r} does not match source {source!r}; "
                f"expected prefix {expected!r}"
            )
        key = _dedupe_key(finding)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return sorted(
        unique,
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 3),
            not bool(item.get("blocking")),
            str(item.get("id") or ""),
        ),
    )


def merge_node(state: dict) -> dict:
    """Replace the reducer channel with one deduplicated, ordered list."""
    merged = merge_findings(list(state.get("findings") or []))
    return {
        "findings": Overwrite(merged),
        "stages": [
            stage_report(MERGE_STAGE, status="done", produced=len(merged), model_calls=0)
        ],
    }


__all__ = ["MERGE_STAGE", "merge_findings", "merge_node"]
