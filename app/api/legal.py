"""HTTP surface for the legal review module (`/legal/*`).

L1 slice: synchronous legal advice (`modes=["legal"]`) via the statute service, in-memory. The
async worker and persistence are L2. The deterministic/semantic engines are not part of this module.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.legal_review.contracts import ReviewCreate, ReviewReport, ReviewRun
from app.legal_review.service import create_review
from app.shared.ports import Principal

router = APIRouter(prefix="/legal", tags=["legal"])

# In-memory store for the L1 slice; replaced by Postgres in L2.
_REPORTS: dict[str, ReviewReport] = {}


class ReviewSubmit(ReviewCreate):
    pass


@router.post("/reviews", status_code=202, response_model=ReviewRun)
def submit_review(submit: ReviewSubmit, request: Request, response: Response) -> ReviewRun:
    # Reuse the same statute instance the assistant service already built (design D2); unset means
    # "no statute leg", which the legal mapper reports as `failed`, never as an empty pass.
    assistant = getattr(request.app.state, "assistant", None)
    statute = getattr(assistant, "statute", None) if assistant is not None else None
    principal = getattr(request.state, "principal", None) or Principal(
        user_id="user_demo_01", workspace_id=submit.workspace_id
    )
    run, report = create_review(submit, statute=statute, principal=principal)
    _REPORTS[report.report_id] = report
    response.headers["Location"] = f"/legal/reports/{report.report_id}"
    return run


@router.get("/reports/{report_id}", response_model=ReviewReport)
def get_report(report_id: str) -> ReviewReport:
    report = _REPORTS.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="resource_unavailable")
    return report
