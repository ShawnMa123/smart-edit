"""`gate` command: ask one protected operation about the current candidate.

The audit stage produces the report; it does not decide anything. A gate decision exists only because
someone named an operation, and the decision binds the snapshot digest it was asked about.
"""

from __future__ import annotations

from app.audit.gate import evaluate, store_decision
from app.audit.snapshot import snapshot_digest


def current_template_digest(report: dict) -> str | None:
    """Hash of the published template the report claims to have used, as it exists *now*.

    A template edit between audit and approval must invalidate the report (design D20). With no
    template requested there is nothing to compare; a template that is no longer published is a
    missing source, which can never match the recorded hash.
    """
    baseline = (report or {}).get("template") or {}
    template_id = baseline.get("template_id")
    if not baseline.get("requested") or baseline.get("synthetic") or not template_id:
        return None
    from app.rules.templates import load_templates

    for pack in load_templates():
        if pack.template_id == template_id and pack.version == str(baseline.get("version")):
            return pack.content_sha256
    return f"missing:{template_id}@{baseline.get('version')}"


def gate_node(
    state: dict, operation: str, *, candidate_digest: str | None = None
) -> dict:
    """Return `{"gate": decision}` for `operation`; unknown operations raise `GateError`.

    The server owns the candidate digest. A caller-supplied digest is only an assertion that the
    report it saw is current: it can never replace the hash of the state being decided. If it
    differs, the audit report is stale and the gate answers `indeterminate`.
    """
    digest = snapshot_digest(state)
    report = ((state.get("verification") or {}).get("audit") or {})
    decision = evaluate(
        state,
        operation,
        digest,
        dispositions=state.get("dispositions") or (),
        client_digest=candidate_digest,
        template_digest=current_template_digest(report),
    )
    return store_decision(state, decision)
