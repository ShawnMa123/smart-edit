"""Pure proposal validation and text application (no HTTP, no SQLite)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.automation.schemas import (
    Anchor,
    ChangeProposal,
    FixtureProposalCreate,
    ProposalContext,
    ProposalPreview,
    ReplaceTextOperation,
    ReviewReceipt,
)
from app.documents.errors import HostError
from app.documents.projection import (
    project_document,
    quote_sha256,
    replace_text_in_document,
    sha256_text,
)


def _invalid(message: str, code: str = "invalid_operation") -> HostError:
    return HostError(422, code, message)


def validate_structure(proposal: ChangeProposal, draft: dict[str, Any]) -> None:
    """Reject anything that cannot be applied exactly to this draft head (no review check)."""
    if proposal.context.content_sha256 != draft["text_sha256"]:
        raise HostError(409, "stale_context", "the proposal was generated from another head")

    projection = project_document(json.loads(draft["content_json"]))
    spans = {span.node_id: span for span in projection.blocks}
    ranged: list[tuple[int, int]] = []
    for operation in proposal.operations:
        anchor = operation.anchor
        if anchor.snapshot_id != proposal.context.content_sha256:
            raise _invalid("anchor snapshot does not match the proposal baseline", "invalid_reference")
        span = spans.get(anchor.node_id)
        if span is None:
            raise _invalid(f"unknown node {anchor.node_id!r}", "invalid_reference")
        if not (span.start_cp <= anchor.start_cp < anchor.end_cp <= span.end_cp):
            raise _invalid("anchor leaves its block", "invalid_reference")
        quote = projection.text[anchor.start_cp:anchor.end_cp]
        if quote_sha256(quote) != anchor.quote_sha256:
            raise _invalid("anchor quote does not match the baseline text", "anchor_mismatch")
        if not operation.replacement_text:
            raise _invalid("replace_text needs a non-empty replacement", "invalid_value")
        if operation.replacement_text == quote:
            raise _invalid("replacement does not change the text", "no_changes")
        ranged.append((anchor.start_cp, anchor.end_cp))

    ordered = sorted(ranged)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise _invalid("operations overlap", "overlapping_operations")


def validate_operations(proposal: ChangeProposal, draft: dict[str, Any]) -> None:
    """Reject anything that cannot be applied exactly to this draft head."""
    if proposal.review_receipt.verdict != "pass":
        raise HostError(409, "review_required", "the proposal has no passing review receipt")
    validate_structure(proposal, draft)


def apply_operations(
    document: dict[str, Any], text: str, operations: list[ReplaceTextOperation]
) -> tuple[dict[str, Any], str]:
    """Apply operations from the end so earlier offsets stay valid."""
    updated = document
    for operation in sorted(operations, key=lambda item: item.anchor.start_cp, reverse=True):
        updated = replace_text_in_document(
            updated,
            operation.anchor.start_cp,
            operation.anchor.end_cp,
            operation.replacement_text,
        )
    return updated, project_document(updated).text


def build_inverse_operations(
    before_text: str, after_text: str, operations: list[ReplaceTextOperation]
) -> list[dict[str, Any]]:
    """Build the reverse of each operation against the new head (undo writes a new revision)."""
    inverse: list[dict[str, Any]] = []
    for operation in sorted(operations, key=lambda item: item.anchor.start_cp, reverse=True):
        original = before_text[operation.anchor.start_cp:operation.anchor.end_cp]
        replacement = operation.replacement_text
        start = operation.anchor.start_cp
        end = start + len(replacement)
        inverse.append(
            {
                "op": "replace_text",
                "anchor": {
                    "snapshot_id": sha256_text(after_text),
                    "node_id": operation.anchor.node_id,
                    "start_cp": start,
                    "end_cp": end,
                    "quote_sha256": quote_sha256(replacement),
                },
                "replacement_text": original,
            }
        )
    return inverse


def _find_target(
    projection_text: str, spans: list[Any], search_text: str | None
) -> tuple[int, str, str]:
    if search_text:
        start = projection_text.find(search_text)
        if start < 0:
            raise _invalid("the fixture search text does not occur in the draft", "invalid_value")
        end = start + len(search_text)
        containing = [
            span
            for span in spans
            if span.start_cp <= start and end <= span.end_cp and "." not in span.node_id
        ]
        if not containing:
            raise _invalid("the fixture search text crosses a block boundary", "invalid_reference")
        return start, projection_text[start:end], containing[0].node_id

    for span in spans:
        if "." in span.node_id:
            continue
        if span.end_cp > span.start_cp:
            quote = projection_text[span.start_cp:span.end_cp]
            return span.start_cp, quote, span.node_id
    raise _invalid("the draft has no text to anchor a fixture proposal", "invalid_value")


def build_fixture_proposal(
    draft: dict[str, Any],
    payload: FixtureProposalCreate,
    *,
    proposal_id: str,
    now: datetime | None = None,
    risk_flags: list[str] | None = None,
) -> ChangeProposal:
    """Deterministic fixture proposal: no model, no hidden content."""
    document = json.loads(draft["content_json"])
    projection = project_document(document)
    start, quote, node_id = _find_target(
        projection.text, list(projection.blocks), payload.search_text
    )
    end = start + len(quote)
    stamp = now or datetime.now(timezone.utc)
    return ChangeProposal(
        proposal_id=proposal_id,
        context=ProposalContext(
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            revision=int(draft["revision"]),
            content_sha256=draft["text_sha256"],
            variables_version=int(draft["variables_version"]),
            authorization_version="auth-demo-1",
        ),
        operations=[
            ReplaceTextOperation(
                op="replace_text",
                anchor=Anchor(
                    snapshot_id=draft["text_sha256"],
                    node_id=node_id,
                    start_cp=start,
                    end_cp=end,
                    quote_sha256=quote_sha256(quote),
                ),
                replacement_text=payload.replacement_text,
            )
        ],
        preview=ProposalPreview(
            before_text=quote,
            after_text=payload.replacement_text,
            summary="fixture replace_text — deterministic demo only",
        ),
        risk_flags=list(risk_flags or []),
        review_receipt=ReviewReceipt(
            receipt_id="review_fixture_01",
            verdict="pass",
            validator_version="fixture-v1",
            checked_claim_ids=["claim_fixture_01"],
        ),
        expires_at=(stamp + timedelta(seconds=payload.expires_in_seconds)).isoformat(),
    )


__all__ = [
    "apply_operations",
    "build_fixture_proposal",
    "build_inverse_operations",
    "validate_operations",
]