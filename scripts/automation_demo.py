"""Deterministic automation demo: fixture proposal -> accept -> apply -> undo.

Run: `.venv/bin/python scripts/automation_demo.py`

No HTTP, no model, no external system. The database is in-memory unless SMART_EDIT_HOST_DB is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.automation.run_schemas import RunCreate
from app.automation.schemas import (
    ApplyRequest,
    ChangeProposal,
    ProposalDecision,
    UndoRequest,
)
from app.documents.bootstrap import build_host_services
from app.shared.ports import Principal

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "automation" / "replace_text.json"


def main() -> int:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    host = build_host_services(
        db_path=os.environ.get("SMART_EDIT_HOST_DB", ":memory:"), mode="test"
    )
    principal = Principal(user_id="user_demo_01", workspace_id="ws_demo_01")
    draft = host.store.create_document(
        workspace_id=principal.workspace_id,
        owner_user_id=principal.user_id,
        title=payload["document"]["title"],
        text=payload["document"]["text"],
    )
    lock = host.store.acquire_lock(
        draft_id=draft["draft_id"], owner_user_id=principal.user_id, lease_seconds=120
    )
    run = host.runs.create(
        principal,
        RunCreate(
            task_type="rewrite",
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            input={
                "intent": "replace_text",
                "search_text": payload["proposal"]["search_text"],
                "replacement_text": payload["proposal"]["replacement_text"],
            },
        ),
        "demo-run",
        "demo",
    )
    host.runs.execute(run.run_id)
    finished = host.runs.get(principal, run.run_id)
    if not finished.result_id:
        raise RuntimeError(f"run did not produce a result: {finished.status}")
    result = host.runs.result(principal, finished.result_id)
    if result.outcome != "proposal_ready":
        raise RuntimeError(f"run outcome: {result.outcome}")
    proposal = ChangeProposal.model_validate(result.payload)
    accepted = host.automation.decide(
        principal,
        proposal.proposal_id,
        ProposalDecision(decision="accepted", reason="fixture demo"),
        proposal.revision,
        "demo",
    )
    receipt = host.automation.apply(
        principal,
        proposal.proposal_id,
        ApplyRequest(
            proposal_id=proposal.proposal_id,
            expected_snapshot_id=proposal.context.content_sha256,
            expected_draft_revision=proposal.context.revision,
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
            acknowledged_risk_codes=list(proposal.risk_flags),
        ),
        "demo-apply",
        "demo",
    )
    applied = host.store.get_draft(draft["draft_id"])
    undo = host.automation.undo(
        principal,
        receipt["receipt_id"],
        UndoRequest(
            expected_draft_revision=receipt["new_revision"],
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
        ),
        "demo-undo",
        "demo",
    )
    restored = host.store.get_draft(draft["draft_id"])

    print(
        json.dumps(
            {
                "fixture": "fixture-backed replace_text; no model",
                "proposal": {
                    "disposition": accepted.disposition,
                    "before": proposal.preview.before_text,
                    "after": proposal.preview.after_text,
                },
                "apply": {
                    "receipt_id": receipt["receipt_id"],
                    "previous_revision": receipt["previous_revision"],
                    "new_revision": receipt["new_revision"],
                    "text": applied["text"] if applied else None,
                },
                "undo": {
                    "reversal_of": undo["reversal_of_receipt_id"],
                    "new_revision": undo["new_revision"],
                    "text": restored["text"] if restored else None,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())