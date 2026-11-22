"""FastAPI application for one run's transport.

Spec: `openspec/changes/frontend-console/specs/console-api/spec.md`
Design: `openspec/changes/frontend-console/design.md` D1, D3, D5, D7.

Three endpoints only: create a run, trigger a stage, read a run. `HITL` / `resume` / `events` belong
to `poc-skeleton` §8-§9 once the graph exists.
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
from app.api.developer import router as developer_router
from app.api.documents import router as documents_router
from app.api.legal import router as legal_router
from app.api.envelope import to_envelope
from app.api.errors import ApiFailure, IncompleteResult, error_body
from app.api.organization import router as organization_router
from app.assistant.bootstrap import build_services
from app.assistant.errors import AssistantError
from app.assistant.service import AssistantService
from app.documents.bootstrap import build_host_services
from app.documents.errors import HostError
from app.identity.authorization import begin_request_cache, end_request_cache
from app.identity.bootstrap import build_identity_services
from app.identity.errors import CsrfRejected, IdentityError
from app.identity.principal import has_csrf_signal, is_public_path, requires_csrf
from app.identity.resources import DocumentAccess
from app.llm import resolve_llm
from app.logging_setup import get_logger
from app.parsing.extraction_profile import ProfileError
from app.runs import RunStore, UnknownRun
from app.runtime import UnknownStage, execute_chain, resolve_extraction_profile
from app.standalone import plan_standalone
from app.stages import AGENT_SPECS

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


async def _read_submission(request: Request) -> tuple[list[tuple[str, str, bytes]], str | None]:
    """Accept JSON `{text}` or multipart (`files` + `text`); anything else is an empty submission."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await request.json()
        text = payload.get("text") if isinstance(payload, dict) else None
        return [], (str(text) if text else None)

    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        uploads: list[tuple[str, str, bytes]] = []
        for value in form.getlist("files"):
            read = getattr(value, "read", None)
            if read is None:
                continue
            name = getattr(value, "filename", None) or "upload.bin"
            mime = getattr(value, "content_type", None) or "application/octet-stream"
            uploads.append((name, mime, await read()))
        raw_text = form.get("text")
        text = str(raw_text) if raw_text else None
        return uploads, text

    return [], None


def create_app(
    *,
    store: RunStore | None = None,
    llm=_UNSET,
    runs_dir: str | Path | None = None,
    assistant_services=None,
    assistant_deadline_seconds: int = 120,
    host_services=None,
    identity_services=None,
) -> FastAPI:
    """Build the app. `llm` overrides provider resolution (tests inject a fixture or `None`)."""
    app = FastAPI(title="smart-edit console API", version="0.1.0")
    app.state.store = store if store is not None else RunStore(runs_dir)
    app.state.llm = resolve_llm() if llm is _UNSET else llm
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
    app.state.automation_registry = _build_automation_registry(host, assistant_services)
    app.include_router(auth_router)
    app.include_router(organization_router)
    app.include_router(activity_router)
    app.include_router(approvals_router)
    app.include_router(developer_router)
    app.include_router(assistant_router)
    app.include_router(documents_router)
    app.include_router(automation_router)
    app.include_router(legal_router)

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
        fields = [
            {"field": ".".join(str(part) for part in error.get("loc", [])), "code": str(error.get("type"))}
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
    async def create_run(request: Request) -> JSONResponse:
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
                    "file_id": f"F-{digest[:8]}",
                    "filename": path.name,
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
                    "file_id": f"F-{digest[:8]}",
                    "filename": path.name,
                    "mime": "text/plain",
                    "path": str(path),
                    "sha256": digest,
                }
            )

        return JSONResponse(status_code=201, content=to_envelope(state))

    @app.post("/runs/{thread_id}/stages/{stage}")
    async def trigger_stage(
        thread_id: str,
        stage: str,
        template: str | None = None,
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

        plan = plan_standalone(stage, state)
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

    @app.get("/runs/{thread_id}")
    async def read_run(thread_id: str) -> dict:
        return to_envelope(app.state.store.get(thread_id))

    return app


app = create_app()