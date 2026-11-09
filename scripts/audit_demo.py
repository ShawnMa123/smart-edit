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
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # allow `python scripts/audit_demo.py` from the repo root
    sys.path.insert(0, str(ROOT))

from app.audit.gate import evaluate_gate  # noqa: E402
from app.audit.policy import OPERATIONS, POLICY_REVISION, START_APPROVAL, SUBMIT_VERSION  # noqa: E402
from app.audit.runner import audit_state  # noqa: E402
from app.rules.bundles import load_bundles  # noqa: E402
from app.rules.schema import load_schema  # noqa: E402
from app.rules.templates import load_templates  # noqa: E402
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
    templates = load_templates()
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
        "templates": [
            {
                "template_id": template.template_id,
                "version": template.version,
                "sha256": template.content_sha256,
                "synthetic": template.synthetic,
                "fields": len(template.fields),
                "clauses": len(template.clauses),
                "declarations": len(template.declarations),
            }
            for template in templates
        ],
        "template_runs": _template_runs(templates),
        "runs": runs,
        "stale_after_edit": {
            "decision": stale_gate["decision"],
            "reason_codes": stale_gate["reason_codes"],
        },
    }


TEMPLATE_DOC_VALUES = {**DOC_VALUES, "beneficiary_name": "Adidas AG"}
TEMPLATE_TEXT = "\n".join(
    [
        "DEMAND GUARANTEE",
        *(f"{key}: {value}" for key, value in TEMPLATE_DOC_VALUES.items()),
        "Origin Country: VN",
        "Payment shall be made in USD within 30 days of presentation.",
        "This guarantee is governed by the laws of England and Wales.",
        "We confirm the funds are from lawful sources.",
    ]
)


def _template_state() -> dict:
    """A document whose counterparty matches the shipped pack, and which satisfies its expectations."""
    state = _state()
    state["fields"]["beneficiary_name"] = _field("beneficiary_name", "Adidas AG")
    state["extra_fields"] = {"origin_country": _field("origin_country", "VN")}
    state["docs"] = [{"file_id": "F-1", "full_text": TEMPLATE_TEXT}]
    return state


def _template_row(label: str, result: dict) -> dict:
    report = result["report"]
    baseline = report["template"]
    return {
        "label": label,
        "planned": report["planned"],
        "template_units": sum(1 for unit in result["units"] if unit.family == "template"),
        "template_id": baseline["template_id"],
        "version": baseline["version"],
        "synthetic": baseline["synthetic"],
        "requested": baseline["requested"],
        "reason": baseline["reason"],
        "candidates": [candidate["template_id"] for candidate in baseline["candidate_templates"]],
        "conflicts": list(baseline["conflicts"]),
        "outcome": report["outcome"],
        "completion": report["completion"],
        "coverage": report["coverage"],
        "counts": report["counts"],
        "findings": [finding["rule_ref"]["rule_id"] for finding in report["findings"]],
    }


def _template_runs(templates: list) -> list[dict]:
    """Two scenarios: the pack applies, and two packs match so nothing may be chosen."""
    pack = next((item for item in templates if item.published), None)
    if pack is None:
        return []
    matched = audit_state(_template_state(), snapshot_digest="digest-template", templates=[pack])
    ambiguous = audit_state(
        _template_state(),
        snapshot_digest="digest-template",
        templates=[pack, replace(pack, template_id=f"{pack.template_id}-second")],
    )
    return [
        _template_row("template matched", matched),
        _template_row("two templates match", ambiguous),
    ]


def render(payload: dict) -> str:
    lines = [
        "Standards audit group — demo run",
        f"  engine {payload['engine_version']} · policy {payload['policy_revision']} · "
        f"schema {payload['schema_version']} ({payload['schema_fields']} fields)",
    ]
    for bundle in payload["bundles"]:
        lines.append(f"  bundle {bundle['id']} v{bundle['version']} sha256={bundle['sha256']}")
    for template in payload.get("templates") or []:
        lines.append(
            f"  template {template['template_id']} v{template['version']} "
            f"sha256={template['sha256']} synthetic={template['synthetic']} "
            f"(fields {template['fields']} · clauses {template['clauses']} · "
            f"declarations {template['declarations']})"
        )
    lines.append(f"  planned units: {payload['runs'][0]['planned']}")
    lines.append("")

    for run in payload.get("template_runs") or []:
        counts, coverage = run["counts"], run["coverage"]
        lines.append(f"[{run['label']}]")
        lines.append(
            f"  template={run['template_id'] or '—'} v{run['version'] or '—'} "
            f"reason={run['reason'] or '—'} candidates={','.join(run['candidates']) or '—'}"
        )
        lines.append(
            f"  planned={run['planned']} template_units={run['template_units']} "
            f"outcome={run['outcome']} completion={run['completion']} "
            f"assessed={coverage['assessed']} ({coverage['ratio']})"
        )
        lines.append(
            "  counts pass={} finding={} needs_input={} unable={} not_applicable={}".format(
                counts["pass"],
                counts["finding"],
                counts["needs_input"],
                counts["unable_to_assess"],
                counts["not_applicable"],
            )
        )
        lines.append(f"  conflicts: {len(run['conflicts'])} · findings: {', '.join(run['findings']) or '—'}")
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