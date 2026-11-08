#!/usr/bin/env python
"""Print one standards audit end to end: plan, coverage, outcome and gate decisions.

Usage:
    .venv/bin/python scripts/audit_demo.py            # human readable
    .venv/bin/python scripts/audit_demo.py --json     # machine readable (for DEMO.md / CI evidence)

Runs against the **pure engine**: no HTTP, no database and no model call. This is the single command
quoted in `openspec/changes/agent-audit/DEMO.md`; if it prints, the engine works.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # allow `python scripts/audit_demo.py` from the repo root
    sys.path.insert(0, str(ROOT))

from app.audit.gate import evaluate_gate  # noqa: E402
from app.audit.policy import OPERATIONS, POLICY_REVISION, START_APPROVAL, SUBMIT_VERSION  # noqa: E402
from app.audit.runner import audit_state  # noqa: E402
from app.rules.bundles import load_bundles  # noqa: E402
from app.rules.schema import load_schema  # noqa: E402
from app.rules.types import ENGINE_VERSION  # noqa: E402

# A minimal guarantee document whose values match the published `guarantee-core` rule pack.
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
DOC_TEXT = "DEMAND GUARANTEE\n" + "\n".join(f"{key}: {value}" for key, value in DOC_VALUES.items())


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
    return {
        "docs": [{"file_id": "F-1", "full_text": DOC_TEXT}],
        "fields": {
            key: _field(key, value, status=statuses.get(key, "extracted"))
            for key, value in DOC_VALUES.items()
            if key not in omit
        },
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }


def _audit(label: str, state: dict, *, snapshot_digest: str, current_digest: str | None = None) -> dict:
    result = audit_state(state, snapshot_digest=snapshot_digest, current_digest=current_digest)
    report, findings = result["report"], result["findings"]
    gates = {
        operation: evaluate_gate(
            report, operation=operation, candidate_digest=snapshot_digest, findings=findings
        )
        for operation in (START_APPROVAL, SUBMIT_VERSION)
    }
    return {
        "label": label,
        "planned": report["planned"],
        "counts": report["counts"],
        "coverage": report["coverage"],
        "outcome": report["outcome"],
        "completion": report["completion"],
        "freshness": report["freshness"],
        "findings": [finding["rule_ref"]["rule_id"] for finding in findings],
        "gates": {
            operation: {
                "decision": decision["decision"],
                "reason_codes": decision["reason_codes"],
                "open_gaps": decision["open_gaps"],
            }
            for operation, decision in gates.items()
        },
    }


def build_report() -> dict:
    schema = load_schema()
    bundles = load_bundles()
    runs = [
        _audit("clean document", _state(), snapshot_digest="digest-clean"),
        _audit(
            "missing guarantee_amount",
            _state(omit=("guarantee_amount",)),
            snapshot_digest="digest-missing",
        ),
        _audit(
            "every value inferred",
            _state(statuses={key: "inferred" for key in DOC_VALUES}),
            snapshot_digest="digest-inferred",
        ),
    ]
    stale_gate = evaluate_gate(
        audit_state(_state(), snapshot_digest="digest-clean")["report"],
        operation=START_APPROVAL,
        candidate_digest="digest-after-edit",
    )
    return {
        "engine_version": ENGINE_VERSION,
        "policy_revision": POLICY_REVISION,
        "schema_version": schema.version,
        "schema_fields": len(schema.fields),
        "bundles": [
            {"id": bundle.bundle_id, "version": bundle.version, "sha256": bundle.content_sha256}
            for bundle in bundles
        ],
        "operations": list(OPERATIONS),
        "runs": runs,
        "stale_after_edit": {
            "decision": stale_gate["decision"],
            "reason_codes": stale_gate["reason_codes"],
        },
    }


def render(payload: dict) -> str:
    lines = [
        "Standards audit group — demo run",
        f"  engine {payload['engine_version']} · policy {payload['policy_revision']} · "
        f"schema {payload['schema_version']} ({payload['schema_fields']} fields)",
    ]
    for bundle in payload["bundles"]:
        lines.append(f"  bundle {bundle['id']} v{bundle['version']} sha256={bundle['sha256']}")
    lines.append(f"  planned units: {payload['runs'][0]['planned']}")
    lines.append("")

    for run in payload["runs"]:
        counts, coverage = run["counts"], run["coverage"]
        lines.append(f"[{run['label']}]")
        lines.append(
            f"  outcome={run['outcome']} completion={run['completion']} freshness={run['freshness']} "
            f"assessed={coverage['assessed']}/{run['planned']} ({coverage['ratio']})"
        )
        lines.append(
            "  counts pass={} finding={} not_applicable={} needs_input={} unable={} failed={}".format(
                counts["pass"],
                counts["finding"],
                counts["not_applicable"],
                counts["needs_input"],
                counts["unable_to_assess"],
                counts["failed"],
            )
        )
        lines.append(f"  findings: {', '.join(run['findings']) or '—'}")
        for operation, gate in run["gates"].items():
            reasons = ",".join(gate["reason_codes"]) or "—"
            lines.append(
                f"  gate {operation:<15} -> {gate['decision']:<13} reasons={reasons} "
                f"open_gaps={gate['open_gaps']}"
            )
        lines.append("")

    stale = payload["stale_after_edit"]
    lines.append("[edited after the audit]")
    lines.append(
        f"  gate {START_APPROVAL} on a report for digest-clean, asked about digest-after-edit "
        f"-> {stale['decision']} ({', '.join(stale['reason_codes']) or '—'})"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one standards audit and print the outcome.")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    payload = build_report()
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())