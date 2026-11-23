"""FastAPI application for one run's transport.

Spec: `openspec/changes/frontend-console/specs/console-api/spec.md`
Design: `openspec/changes/frontend-console/design.md` D1, D3, D5, D7.

The original five console endpoints (create, trigger a stage, ask the gate, append a disposition,
read a run). The additive `poc-skeleton` §8-§9 control plane sits beside them: `POST /run`,
`POST /resume`, `GET /events`, and `POST /runs?autostart=true`. Keeping both means the shipped
frontend keeps its exact envelope while the graph can be driven by tests and operators.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.assistant import router as assistant_router
from app.api.activity import router as activity_router
from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.automation import router as automation_router
from app.api.conformance import router as conformance_router
from app.api.developer import router as developer_router
from app.api.documents import router as documents_router
from app.api.legal import router as legal_router
from app.api.envelope import to_envelope
from app.api.errors import ApiFailure, IncompleteResult, error_body
from app.api.organization import router as organization_router
from app.assistant.bootstrap import build_services
from app.assistant.errors import AssistantError
from app.assistant.service import AssistantService
from app.audit.disposition import DispositionError, append_event, latest
from app.audit.gate import GateError
from app.audit.policy import OPERATIONS
from app.documents.bootstrap import build_host_services
from app.documents.errors import HostError
from app.identity.authorization import begin_request_cache, end_request_cache
from app.identity.bootstrap import build_identity_services
from app.identity.errors import CsrfRejected, IdentityError
from app.identity.principal import has_csrf_signal, is_public_path, requires_csrf
from app.identity.resources import DocumentAccess
from app.llm import resolve_llm
from app.logging_setup import get_logger
from app.nodes.audit import AUDIT_AGENT, AUDIT_STAGE
from app.nodes.gate import gate_node
from app.parsing.extraction_profile import ProfileError
from app.runner import Runner
from app.runs import RunStore, UnknownRun
from app.runtime import UnknownStage, execute_chain, merge_update, resolve_extraction_profile
from app.standalone import plan_standalone
from app.stages import AGENT_SPECS
from app.trail import record

_UNSET = object()
logger = get_logger("api")


def _authorization_version(store, workspace_id: str) -> str | None:
    """Current org authorization version for a workspace; used by automation applicability."""
    if store is None:
        return None
    organization = store.get_org_by_workspace(workspace_id)
    if not organization:
        return None
    version = store.authorization_version(organization["org_id"])
    return f"org:{organization['org_id']}:{version}" if version is not None else None


def _build_automation_registry(host, assistant_services) -> object:
    """Server-side template registry + downstream dispatch, reusing the approved model gateway."""
    from app.automation.registry import AutomationRegistry

    settings = getattr(assistant_services, "settings", None)
    return AutomationRegistry(
        host.store,
        documents=getattr(host, "documents", None),
        gateway=getattr(assistant_services, "gateway", None),
        approved=bool(getattr(settings, "approved_processor", False)),
        model_label=getattr(settings, "processor_label", None),
    )


def _build_legal_service(host, assistant_services, *, store) -> object:
    """Wire the legal module to the document host, statute retriever and composer it already has.

    One composer instance keeps the provider client, timeouts and error codes in one place; when the
    gateway cannot emit JSON (fixture mode) `LegalComposer.available` is False and the legal leg
    reports `composer_unavailable` instead of returning a clean pass.
    """
    from app.legal_review.compose import LegalComposer
    from app.legal_review.scan import ScanSettings
    from app.legal_review.service import LegalService
    from app.legal_review.store import LegalStore

    settings = ScanSettings.from_env()
    gateway = getattr(assistant_services, "gateway", None)
    assistant_settings = getattr(assistant_services, "settings", None)
    egress = getattr(assistant_services, "egress", None)
    redact = None
    if egress is not None and getattr(egress, "loaded", False) and hasattr(egress, "redact"):
        redact = getattr(egress, "redact")
    composer = LegalComposer(
        gateway,
        approved=bool(getattr(assistant_settings, "approved_processor", False)),
        timeout=settings.compose_timeout,
        max_evidence=settings.max_evidence,
        redact=redact,
    )
    db_path = os.environ.get("SMART_EDIT_LEGAL_DB") or str(
        Path(getattr(store, "runs_dir", "runs")) / "legal.db"
    )
    return LegalService(
        store=LegalStore(db_path),
        statute=getattr(assistant_services, "statute", None),
        composer=composer,
        documents=getattr(host, "documents", None),
        settings=settings,
    )


def _build_conformance_service(host, assistant_services, *, store) -> object:
    """Wire the conformance audit to the document host and the approved Doubao composer.

    Same composer contract as the legal scan: no `compose_json` (fixture composer) or no approved
    processor means `available` is False, and the report says `unable_to_assess` instead of passing.
    """
    from app.conformance.compose import ConformanceComposer
    from app.conformance.service import ConformanceService, Settings
    from app.conformance.store import ConformanceStore

    settings = Settings.from_env()
    gateway = getattr(assistant_services, "gateway", None)
    assistant_settings = getattr(assistant_services, "settings", None)
    composer = ConformanceComposer(
        gateway,
        approved=bool(getattr(assistant_settings, "approved_processor", False)),
        timeout=settings.timeout,
    )
    db_path = os.environ.get("SMART_EDIT_CONFORMANCE_DB") or str(
        Path(getattr(store, "runs_dir", "runs")) / "conformance.db"
    )
    return ConformanceService(
        documents=getattr(host, "documents", None),
        composer=composer,
        store=ConformanceStore(db_path),
        settings=settings,
    )


def _read_plan_refusal(plan: dict) -> ApiFailure:
    """Translate `plan_standalone()`'s vocabulary into the client contract (D5)."""
    if plan.get("error") == "unknown_stage":
        return ApiFailure(
            409,
            "unknown_stage",
            plan.get("detail") or "unregistered stage target",
            {"registered": plan.get("registered") or []},
        )
    return ApiFailure(
        409,
        "REFUSED",
        plan.get("detail") or "prerequisites are not satisfied",
        {"missing": plan.get("missing") or []},
    )


def _find_finding(state: dict, finding_id: str) -> dict | None:
    """A disposition may target a contract finding or the audit's own copy (which carries gate type)."""
    for finding in state.get("findings") or []:
        if finding.get("id") == finding_id:
            return finding
    verification = state.get("verification") or {}
    report = verification.get("audit") if isinstance(verification, dict) else None
    for finding in (report or {}).get("findings") or []:
        if finding.get("id") == finding_id:
            return finding
    return None


async def _read_object(request: Request) -> dict:
    """Read one JSON object; a non-object body is a client error, never an empty request."""
    try:
        payload = await request.json()
    except ValueError as exc:
        raise ApiFailure(400, "INVALID_BODY", "request body must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ApiFailure(400, "INVALID_BODY", "request body must be a JSON object")
    return payload


async def _read_submission(request: Request) -> tuple[list[tuple[str, str, bytes]], str | None]:
    """Accept JSON `{text}` or multipart (`files` + `text`); malformed input is a 400.

    `text` is a string by contract: coercing a mapping or a list would hand the pipeline a Python
    repr and call it source text.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError as exc:
            raise ApiFailure(400, "INVALID_BODY", "request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            # A scalar/array body carries no `text`; the create endpoint reports EMPTY_SUBMISSION.
            return [], None
        text = payload.get("text")
        if text is not None and not isinstance(text, str):
            raise ApiFailure(400, "INVALID_BODY", "`text` must be a string")
        return [], (text or None)

    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        try:
            form = await request.form()
        except Exception as exc:  # malformed boundary / truncated body
            raise ApiFailure(400, "INVALID_BODY", "malformed multipart body") from exc
        uploads: list[tuple[str, str, bytes]] = []
        for value in form.getlist("files"):
            read = getattr(value, "read", None)
            if read is None:
                continue
            name = getattr(value, "filename", None) or "upload.bin"
            mime = getattr(value, "content_type", None) or "application/octet-stream"
            uploads.append((name, mime, await read()))
        raw_text = form.get("text")
        if raw_text is not None and not isinstance(raw_text, str):
            raise ApiFailure(400, "INVALID_BODY", "`text` must be a string")
        return uploads, (raw_text or None)

    return [], None


def _next_file_id(state: dict, digest: str) -> str:
    """`F-<digest8>` for the first upload; a suffix keeps identical re-uploads distinct."""
    base = f"F-{digest[:8]}"
    used = {str(item.get("file_id")) for item in state.get("files") or []}
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _control_body(state: dict, result: dict) -> dict:
    """Envelope + one control-plane outcome; `interrupt` is the first pause payload."""
    body = to_envelope(state)
    body["status"] = result.get("status")
    body["interrupt"] = result.get("interrupt")
    body["interrupts"] = result.get("interrupts") or []
    return body


def create_app(
    *,
    store: RunStore | None = None,
    llm=_UNSET,
    runs_dir: str | Path | None = None,
    runner: Runner | None = None,
    checkpointer_path: str | Path | None = None,
    assistant_services=None,
    assistant_deadline_seconds: int = 120,
    host_services=None,
    identity_services=None,
) -> FastAPI:
    """Build the app. `llm` overrides provider resolution (tests inject a fixture or `None`)."""
    app = FastAPI(title="smart-edit console API", version="0.1.0")
    app.state.store = store if store is not None else RunStore(runs_dir)
    app.state.llm = resolve_llm() if llm is _UNSET else llm
    app.state.runner = runner or Runner(
        app.state.store,
        llm=app.state.llm,
        checkpointer_path=checkpointer_path,
    )
    identity = identity_services or build_identity_services()
    app.state.identity = identity
    host = host_services or build_host_services(
        identity=identity.principal, activity=identity.activity
    )
    app.state.host = host
    document_access = None
    if identity.enabled and identity.store is not None and identity.authorization is not None:
        document_access = DocumentAccess(identity.store, host.store, identity.authorization)
        # The host services are built before the identity stack (they own the SQLite store); attach
        # the PG scope checker now that both exist.
        host.documents.authorizer = document_access
        host.automation.authorizer = document_access
        host.runs.authorizer = document_access
        host.approvals.authorizer = document_access
        host.automation.version_provider = lambda workspace_id: _authorization_version(
            identity.store, workspace_id
        )
    assistant_services = assistant_services or build_services(
        identity=identity.principal,
        resource_authorization=document_access,
        evidence_authorizer=document_access,
        activity=identity.activity,
    )
    app.state.assistant = AssistantService(
        assistant_services, deadline_seconds=assistant_deadline_seconds
    )
    app.state.legal = _build_legal_service(host, assistant_services, store=app.state.store)
    app.state.conformance = _build_conformance_service(
        host, assistant_services, store=app.state.store
    )
    app.state.automation_registry = _build_automation_registry(host, assistant_services)
    from app.automation.rules import AutomationRuleService

    app.state.automation_rules = AutomationRuleService(host.store, app.state.automation_registry)
    from app.automation.jobs import AutomationJobService

    app.state.automation_jobs = AutomationJobService(
        host.store,
        app.state.automation_registry,
        activity=identity.activity,
        authorizer=document_access,
    )
    app.include_router(auth_router)
    app.include_router(organization_router)
    app.include_router(activity_router)
    app.include_router(approvals_router)
    app.include_router(developer_router)
    app.include_router(assistant_router)
    app.include_router(documents_router)
    app.include_router(automation_router)
    app.include_router(legal_router)
    app.include_router(conformance_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "auth_mode": identity.settings.mode}

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
        started = time.monotonic()
        begin_request_cache()
        identity_failure: IdentityError | None = None
        if not is_public_path(request.url.path, request.method):
            try:
                request.state.principal = identity.principal.resolve(request)
                if (
                    identity.enabled
                    and requires_csrf(request.method, request)
                    and not has_csrf_signal(request)
                ):
                    raise CsrfRejected()
            except IdentityError as exc:
                identity_failure = exc
        try:
            if identity_failure is not None:
                response = JSONResponse(
                    status_code=identity_failure.status,
                    content=error_body(
                        identity_failure.code, identity_failure.message, identity_failure.detail
                    ),
                )
            else:
                response = await call_next(request)
        except Exception:
            logger.exception(
                "request failed %s %s request=%s",
                request.method, request.url.path, request.state.request_id,
            )
            raise
        finally:
            end_request_cache()
        duration_ms = int((time.monotonic() - started) * 1000)
        # Polling would drown the useful lines; keep reads at DEBUG unless they fail.
        level = logging.INFO if request.method != "GET" else logging.DEBUG
        if response.status_code >= 400:
            level = logging.WARNING
        logger.log(
            level,
            "%s %s -> %d %dms request=%s",
            request.method, request.url.path, response.status_code, duration_ms,
            request.state.request_id,
        )
        api_key = getattr(request.state, "api_key", None)
        if api_key is not None and identity.store is not None:
            try:
                # Logs hold no body/token: method, path, status and latency only (design D8).
                identity.store.append_request_log(
                    api_key_id=api_key["key_id"],
                    org_id=api_key["org_id"],
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    latency_ms=duration_ms,
                )
            except Exception:  # noqa: BLE001 - logging must never break the response
                logger.exception("api request log write failed")
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(IdentityError)
    async def _identity_error(request: Request, exc: IdentityError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.detail)
        )

    @app.exception_handler(AssistantError)
    async def _assistant_error(request: Request, exc: AssistantError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": str(getattr(request.state, "request_id", "")),
                    "retryable": exc.retryable,
                    **({"detail": exc.detail} if exc.detail is not None else {}),
                }
            },
        )

    @app.exception_handler(HostError)
    async def _host_error(request: Request, exc: HostError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": str(getattr(request.state, "request_id", "")),
                    "retryable": exc.retryable,
                    **(dict(exc.detail) if isinstance(exc.detail, dict) else {}),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Validation refusals keep each API family's error contract.

        The legacy console (`/runs…`) returns `{code, message, detail?}`; the newer identity /
        assistant / document / automation APIs nest under `error` and echo the request id.
        """
        if request.url.path == "/runs" or request.url.path.startswith("/runs/"):
            errors = [
                {
                    "loc": [str(part) for part in error.get("loc", ())],
                    "msg": str(error.get("msg") or ""),
                    "type": str(error.get("type") or ""),
                }
                for error in exc.errors()
            ]
            return JSONResponse(
                status_code=422,
                content=error_body(
                    "INVALID_REQUEST", "request validation failed", {"errors": errors}
                ),
            )
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "code": str(error.get("type")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "request fields are invalid",
                    "request_id": str(getattr(request.state, "request_id", "")),
                    "retryable": False,
                    "field_errors": fields,
                }
            },
        )

    @app.exception_handler(ApiFailure)
    async def _api_failure(request: Request, exc: ApiFailure) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=exc.status, content=error_body(exc.code, exc.message, exc.detail)
        )

    @app.exception_handler(UnknownRun)
    async def _unknown_run(request: Request, exc: UnknownRun) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=404,
            content=error_body(
                "unknown_run",
                "this run is not held by the server; run state is process-scoped and does not "
                "survive a restart — start a new run",
                {"thread_id": exc.thread_id},
            ),
        )

    @app.exception_handler(IncompleteResult)
    async def _incomplete(request: Request, exc: IncompleteResult) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=500, content=error_body("INCOMPLETE_RESULT", str(exc)))

    @app.post("/runs", status_code=201)
    async def create_run(request: Request, autostart: bool = False) -> JSONResponse:
        store_: RunStore = app.state.store
        uploads, text = await _read_submission(request)
        if not uploads and not text:
            raise ApiFailure(
                400, "EMPTY_SUBMISSION", "provide at least one file or a non-empty text body"
            )

        thread_id, state = store_.create()

        for filename, mime, data in uploads:
            path, digest = store_.store_upload(thread_id, filename, data)
            state["files"].append(
                {
                    "file_id": _next_file_id(state, digest),
                    "filename": filename,
                    "mime": mime,
                    "path": str(path),
                    "sha256": digest,
                }
            )

        if not uploads and text is not None:
            # Design D7: one parsing path for text and files alike.
            path, digest = store_.store_upload(thread_id, "pasted.txt", text.encode("utf-8"))
            state["files"].append(
                {
                    "file_id": _next_file_id(state, digest),
                    "filename": "pasted.txt",
                    "mime": "text/plain",
                    "path": str(path),
                    "sha256": digest,
                }
            )

        if autostart:
            # Opt-in compatibility with the `poc-skeleton` contract: the create response carries
            # the first review payload. The console keeps its legacy "create, then trigger" flow.
            async with store_.lock(thread_id):
                result = app.state.runner.start(thread_id)
            return JSONResponse(
                status_code=201, content=_control_body(state, result)
            )

        return JSONResponse(status_code=201, content=to_envelope(state))

    @app.post("/runs/{thread_id}/stages/{stage}")
    async def trigger_stage(
        thread_id: str,
        stage: str,
        template: str | None = None,
        input_mode: str = "raw",
        as_of: str | None = None,
        profile: str | None = None,
    ) -> dict:
        """Run a stage chain. `?template=<id>` asks for template-driven audit (design D18).

        `?as_of=YYYY-MM-DD` fixes the audit date (change D5); without it the server's today is used
        and echoed in `verification.audit.as_of`.

        `?profile=<id>` selects a published extraction profile (change D7). Without it, a named
        template's `extraction_profile` applies. Unlike the audit template, an unusable profile is
        **refused**, never silently replaced by the fixture path.

        The query parameter can only *narrow* which published template applies; it can never select a
        version or an unpublished pack.
        """
        store_: RunStore = app.state.store
        state = store_.get(thread_id)

        agent_spec = AGENT_SPECS.get(stage)
        if agent_spec is not None and not agent_spec.standalone:
            # D5: checked before the plan lookup, otherwise `agent4` would read as `unknown_stage`.
            raise ApiFailure(
                403,
                "NOT_STANDALONE",
                f"{stage} cannot be triggered on its own",
                {"agent": stage},
            )

        plan = plan_standalone(stage, state, input_mode=input_mode)
        if plan.get("status") != 200:
            raise _read_plan_refusal(plan)

        extraction_profile = None
        if "extract" in plan["chain"]:
            try:
                extraction_profile = resolve_extraction_profile(
                    state, requested=profile, template_id=template
                )
            except ProfileError as exc:
                raise ApiFailure(400, "invalid_extraction_profile", str(exc)) from exc

        async with store_.lock(thread_id):
            try:
                execute_chain(
                    state,
                    list(plan["chain"]),
                    llm=app.state.llm,
                    template_reference={"template_id": template} if template else None,
                    as_of=as_of,
                    profile=extraction_profile,
                )
            except UnknownStage as exc:
                raise ApiFailure(409, "unknown_stage", str(exc)) from exc

        return to_envelope(state)

    @app.post("/runs/{thread_id}/gate")
    async def ask_gate(thread_id: str, request: Request) -> dict:
        """Ask one protected operation about the current candidate (design D8; gate is a command)."""
        payload = await _read_object(request)
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ApiFailure(
                400,
                "UNKNOWN_OPERATION",
                "operation is missing or unknown",
                {"known_operations": list(OPERATIONS)},
            )

        candidate_digest = payload.get("candidate_digest")
        if candidate_digest is not None and not isinstance(candidate_digest, str):
            raise ApiFailure(
                400,
                "INVALID_DIGEST",
                "candidate_digest must be a string or null",
                {"candidate_digest": candidate_digest},
            )

        store_: RunStore = app.state.store
        store_.get(thread_id)
        async with store_.lock(thread_id):
            state = store_.get(thread_id)
            try:
                update = gate_node(state, operation, candidate_digest=candidate_digest)
            except GateError as exc:  # pragma: no cover - pre-validated above; keeps the contract explicit
                raise ApiFailure(
                    400,
                    "UNKNOWN_OPERATION",
                    str(exc),
                    {"known_operations": list(OPERATIONS)},
                ) from exc
            merge_update(state, update)

        return {
            "thread_id": thread_id,
            "operation": operation,
            "gate": state.get("gate"),
            "verification": state.get("verification"),
        }

    @app.post("/runs/{thread_id}/findings/{finding_id}/disposition")
    async def dispose_finding(thread_id: str, finding_id: str, request: Request) -> dict:
        """Append one human disposition event; findings are never edited to look resolved."""
        payload = await _read_object(request)
        disposition = payload.get("disposition")
        actor = payload.get("actor")
        reason = payload.get("reason")

        store_: RunStore = app.state.store
        store_.get(thread_id)
        async with store_.lock(thread_id):
            state = store_.get(thread_id)
            finding = _find_finding(state, finding_id)
            if finding is None:
                raise ApiFailure(
                    404,
                    "UNKNOWN_FINDING",
                    f"unknown finding {finding_id!r}",
                    {"finding_id": finding_id},
                )

            try:
                report = (state.get("verification") or {}).get("audit") or {}
                events = append_event(
                    state.get("dispositions") or [],
                    finding_id=finding_id,
                    disposition=disposition if isinstance(disposition, str) else "",
                    actor=actor if isinstance(actor, str) else "",
                    severity=finding.get("severity"),
                    reason=reason if isinstance(reason, str) else None,
                    snapshot_digest=report.get("snapshot_digest"),
                )
            except DispositionError as exc:
                raise ApiFailure(
                    400, exc.code, str(exc), {"finding_id": finding_id}
                ) from exc

            # Append-only: earlier events are untouched; the finding itself is untouched as well.
            state["dispositions"] = events
            # A decision taken before this event is stale, not reusable (rule-audit gate contract).
            state["gate"] = None
            event = events[-1]
            merge_update(
                state,
                record(
                    state,
                    agent=AUDIT_AGENT,
                    stage=AUDIT_STAGE,
                    op="transform",
                    detail={
                        "finding_id": finding_id,
                        "disposition": event["disposition"],
                        "actor": event["actor"],
                    },
                ),
            )

        return {
            "thread_id": thread_id,
            "finding_id": finding_id,
            "events": events,
            "latest": latest(events, finding_id, report.get("snapshot_digest")),
        }

    @app.post("/runs/{thread_id}/run")
    async def run_graph(thread_id: str) -> dict:
        """Run the checkpointed main graph to its first `interrupt` (or `END`).

        The five frontend endpoints keep their legacy chain semantics; this endpoint is the
        additive control plane the `poc-skeleton` graph needs. It never bypasses the per-run lock.
        """
        store_: RunStore = app.state.store
        state = store_.get(thread_id)
        async with store_.lock(thread_id):
            result = app.state.runner.start(thread_id)
        return _control_body(state, result)

    @app.post("/runs/{thread_id}/resume")
    async def resume_run(thread_id: str, request: Request) -> dict:
        """Resume one `hitl` interrupt. The same payload is applied exactly once."""
        store_: RunStore = app.state.store
        state = store_.get(thread_id)
        payload = await _read_object(request)
        async with store_.lock(thread_id):
            result = app.state.runner.resume(thread_id, payload)
        return _control_body(state, result)

    @app.get("/runs/{thread_id}/events")
    async def read_events(thread_id: str) -> dict:
        """Oldest-first node / stage / trail timeline for the replay view."""
        store_: RunStore = app.state.store
        store_.get(thread_id)
        return {"thread_id": thread_id, "events": app.state.runner.events(thread_id)}

    @app.get("/runs/{thread_id}")
    async def read_run(thread_id: str) -> dict:
        return to_envelope(app.state.store.get(thread_id))

    return app


app = create_app()