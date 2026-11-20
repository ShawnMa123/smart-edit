"""HTTP surface for the legal review module (`/legal/*`).

L1 slice: synchronous, deterministic-only, in-memory. The async worker and persistence
are L2. `facts` is carried on the request body for the demo only — the real pipeline will
resolve it from `facts_version_id` against the host (spec §4.1).
"""

from __future__ import annotations

from collections import OrderedDict

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.api.errors import ApiFailure
from app.legal_review.contracts import ReviewCreate, ReviewReport, ReviewRun
from app.legal_review.service import create_review
from app.shared.ports import Principal

router = APIRouter(prefix="/legal", tags=["legal"])

# In-memory store for the L1 slice; replaced by Postgres in L2. Bounded so a long-running demo
# cannot grow without limit; the oldest report is evicted first.
_MAX_REPORTS = 200
_REPORTS: "OrderedDict[str, ReviewReport]" = OrderedDict()


class ReviewSubmit(ReviewCreate):
    # Temporary demo field; the host resolves facts from facts_version_id in the real flow.
    facts: dict = Field(default_factory=dict)


@router.post("/reviews", status_code=202, response_model=ReviewRun)
def submit_review(submit: ReviewSubmit, request: Request, response: Response) -> ReviewRun:
    # Reuse the same statute instance the assistant service already built (design D2); unset means
    # "no statute leg", which the legal mapper reports as `failed`, never as an empty pass.
    assistant = getattr(request.app.state, "assistant", None)
    statute = getattr(assistant, "statute", None) if assistant is not None else None
    principal = getattr(request.state, "principal", None) or Principal(
        user_id="user_demo_01", workspace_id=submit.workspace_id
    )
    run, report = create_review(submit, submit.facts, statute=statute, principal=principal)
    _REPORTS[report.report_id] = report
    _REPORTS.move_to_end(report.report_id)
    while len(_REPORTS) > _MAX_REPORTS:
        _REPORTS.popitem(last=False)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/legal/reports/{report.report_id}"
    return run


@router.get("/reports/{report_id}", response_model=ReviewReport)
def get_report(report_id: str, response: Response) -> ReviewReport:
    report = _REPORTS.get(report_id)
    if report is None:
        # Same `{code, message}` error contract as the rest of the API, not FastAPI's `{detail}`.
        raise ApiFailure(404, "resource_unavailable", "legal report not found")
    response.headers["Cache-Control"] = "no-store"
    return report
