"""`gate` command: ask one protected operation about the current candidate.

The audit stage produces the report; it does not decide anything. A gate decision exists only because
someone named an operation, and the decision binds the snapshot digest it was asked about.
"""

from __future__ import annotations

from app.audit.gate import evaluate, store_decision
from app.audit.snapshot import snapshot_digest


def gate_node(
    state: dict, operation: str, *, candidate_digest: str | None = None
) -> dict:
    """Return `{"gate": decision}` for `operation`; unknown operations raise `GateError`.

    The server owns the candidate digest. A caller-supplied digest is only an assertion that the
    report it saw is current: it can never replace the hash of the state being decided. If it
    differs, the audit report is stale and the gate answers `indeterminate`.
    """
    digest = snapshot_digest(state)
    decision = evaluate(
        state,
        operation,
        digest,
        dispositions=state.get("dispositions") or (),
        client_digest=candidate_digest,
    )
    return store_decision(state, decision)
