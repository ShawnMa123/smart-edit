"""HTTP surface for automation proposals, apply and undo (`/automation`)."""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.automation.run_schemas import AutomationResult, AutomationRun, RunCancel, RunCreate, RunPage
from app.automation.registry_schemas import (
    ConnectorCreate,
    ConnectorPage,
    ConnectorSpecView,
    ConnectorUpdate,
    ConnectorView,
    DispatchPage,
    DispatchPreview,
    DispatchReceipt,
    DispatchRequest,
    MappingUpdate,
    MappingView,
    PreparedPayload,
    PrepareRequest,
    SpecBuildRequest,
    SpecBuildResult,
    SpecParseRequest,
    SpecParseResult,
    SuggestionView,
    TemplateApplyRequest,
    TemplateApplyResult,
    TemplateCreate,
    TemplateDuplicate,
    TemplatePage,
    TemplateUpdate,
    TemplateVariablesUpdate,
    TemplateView,
    TemplateWriteBackRequest,
    TemplateWriteBackResult,
)
from app.automation.schemas import (
    ApplyRequest,
    ProposalDecision,
    UndoRequest,
)
from app.automation.service import AutomationService
from app.documents.errors import HostError, PreconditionRequired
from app.documents.projection import sha256_text

router = APIRouter(prefix="/automation", tags=["automation"])


def _service(request: Request) -> AutomationService:
    return request.app.state.host.automation


def _runs(request: Request):
    return request.app.state.host.runs


def _registry(request: Request):
    registry = getattr(request.app.state, "automation_registry", None)
    if registry is None:
        raise HostError(
            409, "automation_registry_unavailable", "this server has no automation registry"
        )
    return registry


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HostError(401, "auth_required", "the request has no resolved principal")
    return principal


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise HostError(400, "invalid_request", "this operation requires an Idempotency-Key")
    return key


def _revision(request: Request, prefix: str) -> int:
    header = request.headers.get("if-match")
    if not header:
        raise PreconditionRequired(f"If-Match must look like \"{prefix}-<revision>\"")
    value = header.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    expected = f"{prefix}-"
    if not value.startswith(expected):
        raise PreconditionRequired(f"If-Match must look like \"{prefix}-<revision>\"")
    try:
        return int(value[len(expected):])
    except ValueError as exc:
        raise PreconditionRequired("If-Match revision is not a number") from exc


def _hash(payload: dict[str, Any]) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _idempotent(
    request: Request,
    service: AutomationService,
    path: str,
    payload: dict[str, Any],
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    principal = service.principal(request)
    key = _key(request)
    existing = service.host.get_idempotency(principal.user_id, "POST", path, key)
    if existing:
        if existing["request_hash"] != _hash(payload):
            raise HostError(
                409, "idempotency_conflict", "the same idempotency key was reused with another request"
            )
        return json.loads(existing["response_json"])
    result = action()
    service.host.put_idempotency(principal.user_id, "POST", path, key, _hash(payload), result)
    return result


def _headers(response: Response, etag: str) -> None:
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("/runs", status_code=202)
def create_run(
    request: Request,
    response: Response,
    payload: RunCreate,
    background_tasks: BackgroundTasks,
) -> AutomationRun:
    service = _runs(request)
    run = service.create(
        service.principal(request), payload, request.headers.get("idempotency-key"), _request_id(request)
    )
    _headers(response, f"run-{run.revision}")
    response.headers["Location"] = f"/automation/runs/{run.run_id}"
    background_tasks.add_task(service.execute, run.run_id)
    return run


@router.get("/runs", response_model=RunPage)
def list_runs(document_id: str, request: Request) -> RunPage:
    service = _runs(request)
    return RunPage(items=service.list(service.principal(request), document_id))


@router.get("/runs/{run_id}", response_model=AutomationRun)
def get_run(run_id: str, request: Request, response: Response) -> AutomationRun:
    service = _runs(request)
    run = service.get(service.principal(request), run_id)
    _headers(response, f"run-{run.revision}")
    return run


@router.post("/runs/{run_id}/cancel", response_model=AutomationRun)
def cancel_run(
    run_id: str, request: Request, response: Response, payload: RunCancel
) -> AutomationRun:
    service = _runs(request)
    run = service.cancel(
        service.principal(request), run_id, _revision(request, "run"), payload.reason
    )
    _headers(response, f"run-{run.revision}")
    return run


@router.get("/results/{result_id}", response_model=AutomationResult)
def get_result(result_id: str, request: Request, response: Response) -> AutomationResult:
    service = _runs(request)
    result = service.result(service.principal(request), result_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    model = service.get(service.principal(request), proposal_id)
    _headers(response, f"proposal-{model.revision}")
    return model.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/decisions", status_code=201)
def decide_proposal(
    proposal_id: str, request: Request, response: Response, payload: ProposalDecision
) -> dict:
    service = _service(request)
    expected = _revision(request, "proposal")
    path = f"/automation/proposals/{proposal_id}/decisions"
    model = _idempotent(
        request,
        service,
        path,
        payload.model_dump(mode="json"),
        lambda: service.decide(
            service.principal(request), proposal_id, payload, expected, _request_id(request)
        ).model_dump(mode="json"),
    )
    _headers(response, f"proposal-{model['revision']}")
    return model


@router.post("/proposals/{proposal_id}/apply", status_code=201)
def apply_proposal(
    proposal_id: str, request: Request, response: Response, payload: ApplyRequest
) -> dict:
    service = _service(request)
    expected = _revision(request, "draft")
    if expected != payload.expected_draft_revision:
        raise HostError(412, "version_mismatch", "If-Match does not match expected_draft_revision")
    receipt = service.apply(
        service.principal(request),
        proposal_id,
        payload,
        request.headers.get("idempotency-key"),
        _request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/automation/applications/{receipt['receipt_id']}"
    return receipt


@router.post("/applications/{receipt_id}/undo", status_code=201)
def undo_application(
    receipt_id: str, request: Request, response: Response, payload: UndoRequest
) -> dict:
    service = _service(request)
    expected = _revision(request, "draft")
    if expected != payload.expected_draft_revision:
        raise HostError(412, "version_mismatch", "If-Match does not match expected_draft_revision")
    receipt = service.undo(
        service.principal(request),
        receipt_id,
        payload,
        request.headers.get("idempotency-key"),
        _request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return receipt


@router.get("/applications/{receipt_id}")
def get_application(receipt_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    receipt = service.get_receipt(service.principal(request), receipt_id)
    response.headers["Cache-Control"] = "no-store"
    return receipt


# ── server-side template registry (templates → confirmed variables → dispatch) ────────────────
@router.get("/templates", response_model=TemplatePage)
def list_templates(request: Request) -> TemplatePage:
    return TemplatePage(items=_registry(request).list_templates(_principal(request)))


@router.post("/templates", status_code=201, response_model=TemplateView)
def create_template(payload: TemplateCreate, request: Request) -> TemplateView:
    return _registry(request).create_template(_principal(request), payload)


@router.get("/templates/{template_id}", response_model=TemplateView)
def get_template(template_id: str, request: Request) -> TemplateView:
    return _registry(request).get_template(_principal(request), template_id)


@router.post("/templates/{template_id}/variables/suggest", response_model=SuggestionView)
def suggest_template_variables(
    template_id: str, request: Request, use_llm: bool = True
) -> SuggestionView:
    """Deterministic + optional Doubao suggestions. Never persists; the user confirms."""
    return _registry(request).suggest_variables(
        _principal(request), template_id, use_llm=use_llm
    )


@router.put("/templates/{template_id}/variables", response_model=TemplateView)
def save_template_variables(
    template_id: str, payload: TemplateVariablesUpdate, request: Request
) -> TemplateView:
    return _registry(request).save_variables(_principal(request), template_id, payload)


@router.post("/templates/{template_id}/prepare", response_model=PreparedPayload)
def prepare_template_payload(
    template_id: str, payload: PrepareRequest, request: Request
) -> PreparedPayload:
    """Bind confirmed variables to a draft; missing values are reported, never guessed."""
    return _registry(request).prepare(_principal(request), template_id, payload)


@router.put("/templates/{template_id}", response_model=TemplateView)
def rename_template(template_id: str, payload: TemplateUpdate, request: Request) -> TemplateView:
    """Rename a stored version (history keeps the name it was dispatched under)."""
    return _registry(request).rename_template(_principal(request), template_id, payload)


@router.post("/templates/{template_id}/duplicate", status_code=201, response_model=TemplateView)
def duplicate_template(
    template_id: str, payload: TemplateDuplicate, request: Request
) -> TemplateView:
    """Copy the text and the confirmed variables under a new name."""
    return _registry(request).duplicate_template(_principal(request), template_id, payload)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, request: Request) -> Response:
    """Remove one template version; dispatch receipts keep their own snapshot."""
    _registry(request).delete_template(_principal(request), template_id)
    return Response(status_code=204)


@router.post("/templates/{template_id}/apply", status_code=201, response_model=TemplateApplyResult)
def apply_template(
    template_id: str, payload: TemplateApplyRequest, request: Request
) -> TemplateApplyResult:
    """Render the template into a NEW document, filling the confirmed variables."""
    return _registry(request).apply_template(_principal(request), template_id, payload)


@router.post("/templates/{template_id}/write-back", response_model=TemplateWriteBackResult)
def write_back_template(
    template_id: str, payload: TemplateWriteBackRequest, request: Request
) -> TemplateWriteBackResult:
    """Write the values into the CURRENT draft under the caller's lock and expected revision."""
    return _registry(request).write_back(_principal(request), template_id, payload)


@router.post("/spec/parse", response_model=SpecParseResult)
def parse_spec_document(payload: SpecParseRequest, request: Request) -> SpecParseResult:
    """Parse an OpenAPI document with the same code the registry uses (sandbox preview)."""
    return _registry(request).parse_contract(_principal(request), payload.spec)


@router.post("/spec/build", response_model=SpecBuildResult)
def build_spec_body(payload: SpecBuildRequest, request: Request) -> SpecBuildResult:
    """Assemble a request body for a spec + mapping without persisting anything."""
    return _registry(request).build_contract_body(_principal(request), payload)


@router.get("/connectors", response_model=ConnectorPage)
def list_connectors(request: Request) -> ConnectorPage:
    return ConnectorPage(items=_registry(request).list_connectors(_principal(request)))


@router.post("/connectors", status_code=201, response_model=ConnectorView)
def create_connector(payload: ConnectorCreate, request: Request) -> ConnectorView:
    return _registry(request).create_connector(_principal(request), payload)


@router.put("/connectors/{connector_id}", response_model=ConnectorView)
def update_connector(
    connector_id: str, payload: ConnectorUpdate, request: Request
) -> ConnectorView:
    """Edit a target in place; replacing the spec resets the field mapping (new contract)."""
    return _registry(request).update_connector(_principal(request), connector_id, payload)


@router.get("/connectors/{connector_id}/spec", response_model=ConnectorSpecView)
def read_connector_spec(connector_id: str, request: Request) -> ConnectorSpecView:
    """The stored OpenAPI document (fetched on demand; list responses stay small)."""
    return _registry(request).connector_spec(_principal(request), connector_id)


@router.delete("/connectors/{connector_id}", response_model=ConnectorView)
def disable_connector(connector_id: str, request: Request) -> ConnectorView:
    """Soft delete: receipts stay for audit, dispatch can no longer target it."""
    return _registry(request).disable_connector(_principal(request), connector_id)


@router.get("/mappings", response_model=MappingView)
def read_mapping(template_id: str, connector_id: str, request: Request) -> MappingView:
    """The stored (template, connector) mapping; `configured=false` means the panel should suggest."""
    return _registry(request).mapping(_principal(request), template_id, connector_id)


@router.put("/connectors/{connector_id}/mapping", response_model=ConnectorView)
def set_connector_mapping(
    connector_id: str, payload: MappingUpdate, request: Request
) -> ConnectorView:
    """Bind the downstream's request-body fields to template variables (persisted per connector)."""
    return _registry(request).set_mapping(_principal(request), connector_id, payload)


@router.get("/dispatches", response_model=DispatchPage)
def list_dispatches(request: Request, limit: int = 50) -> DispatchPage:
    return DispatchPage(items=_registry(request).list_dispatches(_principal(request), limit=limit))


@router.post("/dispatches/preview", response_model=DispatchPreview)
def preview_dispatch(payload: DispatchRequest, request: Request) -> DispatchPreview:
    """What the call would look like: URL, masked headers, body and issues — no HTTP, no receipt."""
    return _registry(request).preview(_principal(request), payload)


@router.post("/dispatches", status_code=201, response_model=DispatchReceipt)
def dispatch(payload: DispatchRequest, request: Request) -> DispatchReceipt:
    """Perform the outbound call (allow-listed hosts only) and record the receipt."""
    return _registry(request).dispatch(_principal(request), payload)


__all__ = ["router"]