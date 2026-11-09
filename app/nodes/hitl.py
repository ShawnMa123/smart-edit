"""`hitl` node: pause before release, apply human edits, never repeat them.

Spec: `orchestration` -> *人工核对暂停*. Design: `poc-skeleton/design.md` §11.

Hard constraints (violating them double-charges or double-writes):

1. **Nothing before `interrupt()`**: the payload is assembled from state only; no model call,
   no database write, no notification.
2. **Resume is idempotent**: the applied payload's digest is recorded in the trail; the same
   payload arriving twice returns without touching `fields` or `recheck_count`.
3. **No re-parse on resume**: the graph resumes from its checkpoint, and `parse` / `extract`
   are not reachable from `hitl` unless the user asked for `recheck`.

Resume shape: `{"edits": [{"key", "value"}], "recheck": true}`.
"""

from __future__ import annotations

import hashlib
import json

from langgraph.types import interrupt

from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record_many

HITL_STAGE = "hitl"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _field_view(fields: dict | None) -> list[dict]:
    return [
        {
            "key": key,
            "value": value.get("value"),
            "status": value.get("status"),
            "confirmed": bool(value.get("confirmed")),
            "source": value.get("source"),
            "notes": value.get("notes") or [],
        }
        for key, value in sorted((fields or {}).items())
    ]


def _finding_view(findings: list | None) -> list[dict]:
    rank = {"critical": 0, "warn": 1, "info": 2}
    rows = [
        {
            "id": finding.get("id"),
            "source": finding.get("source"),
            "severity": finding.get("severity"),
            "blocking": bool(finding.get("blocking")),
            "message": finding.get("message"),
            "evidence": finding.get("evidence"),
        }
        for finding in findings or []
    ]
    return sorted(
        rows,
        key=lambda row: (rank.get(str(row["severity"]), 3), str(row["id"] or "")),
    )


def _latest_stages(stages: list | None) -> list[dict]:
    by_name: dict[str, dict] = {}
    for report in stages or []:
        by_name[str(report.get("stage"))] = report
    return [
        {
            "stage": report.get("stage"),
            "status": report.get("status"),
            "produced": report.get("produced"),
            "reason": report.get("reason"),
        }
        for _, report in sorted(by_name.items())
    ]


def build_payload(state: dict) -> dict:
    """The self-contained review panel; the client receives nothing else."""
    verification = state.get("verification") or {}
    legal = state.get("legal") or {}
    return {
        "run_id": state.get("run_id"),
        "business_type": state.get("business_type"),
        "fields": _field_view(state.get("fields")),
        "findings": _finding_view(state.get("findings")),
        "legal": {
            "input_mode": legal.get("input_mode"),
            "summary": legal.get("summary"),
            "escalate_to_human": bool(legal.get("escalate_to_human")),
            "coverage": legal.get("coverage"),
        },
        "verification": {
            "verdict": verification.get("verdict"),
            "checks": verification.get("checks") or [],
        },
        "stages": _latest_stages(state.get("stages")),
    }


def _already_applied(state: dict, resume_hash: str) -> bool:
    for entry in state.get("trail") or []:
        if entry.get("stage") != HITL_STAGE:
            continue
        if (entry.get("detail") or {}).get("resume_hash") == resume_hash:
            return True
    return False


def apply_resume(state: dict, resume: object) -> dict:
    """Merge one resume payload into fields; the caller has already checked idempotency."""
    payload = resume if isinstance(resume, dict) else {}
    edits = payload.get("edits") or []
    if not isinstance(edits, list):
        edits = []

    fields = dict(state.get("fields") or {})
    entries: list[dict] = []
    resume_hash = _hash(payload)
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        key = edit.get("key")
        if not isinstance(key, str) or key not in fields:
            # The panel can only edit a field the contract already contains; an unknown key is
            # a client bug, not a new field.
            continue
        old = fields[key]
        old_value = old.get("value")
        new_value = edit.get("value")
        if new_value is not None:
            new_value = str(new_value)
        fields[key] = {
            **old,
            "value": new_value,
            "confirmed": True,
            "edited_by_user": True,
            # Keep the value the system produced, so an auditor can see what the human changed.
            "normalized_from": old_value,
        }
        entries.append(
            {
                "op": "transform",
                "before": old_value,
                "after": new_value,
                "ref": key,
                "detail": {"field": key, "resume_hash": resume_hash, "actor": "human"},
            }
        )

    if not entries:
        entries.append(
            {
                "op": "pass",
                "before": None,
                "after": None,
                "ref": None,
                "detail": {
                    "reason": "human resumed without edits",
                    "resume_hash": resume_hash,
                    "recheck": bool(payload.get("recheck")),
                },
            }
        )

    return {
        "fields": fields,
        "recheck": bool(payload.get("recheck")),
        "recheck_count": int(state.get("recheck_count") or 0) + 1,
        "stages": [
            stage_report(
                HITL_STAGE,
                status="done",
                produced=len([entry for entry in entries if entry["op"] == "transform"]),
                model_calls=0,
            )
        ],
        **record_many(state, agent=SHARED_STAGE_OWNER, stage=HITL_STAGE, entries=entries),
    }


def hitl_node(state: dict) -> dict:
    """Pause with a self-contained payload; on resume apply the edits exactly once."""
    payload = build_payload(state)
    resume = interrupt(payload)
    resume_hash = _hash(resume if isinstance(resume, dict) else {})
    if _already_applied(state, resume_hash):
        # A duplicate resume changes nothing; the graph still continues from the checkpoint.
        return {}
    return apply_resume(state, resume)


__all__ = ["HITL_STAGE", "apply_resume", "build_payload", "hitl_node"]
