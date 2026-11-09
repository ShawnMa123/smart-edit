"""FastAPI application for one run's transport.

Spec: `openspec/changes/frontend-console/specs/console-api/spec.md`
Design: `openspec/changes/frontend-console/design.md` D1, D3, D5, D7.

Five endpoints: create a run, trigger a stage, ask the gate, append a disposition, read a run.
`HITL` / `resume` / `events` belong to `poc-skeleton` §8-§9 once the graph exists.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.envelope import to_envelope
from app.api.errors import ApiFailure, IncompleteResult, error_body
from app.audit.disposition import DispositionError, append_event, latest
from app.audit.gate import GateError
from app.audit.policy import OPERATIONS
from app.llm import resolve_llm
from app.nodes.audit import AUDIT_AGENT, AUDIT_STAGE
from app.nodes.gate import gate_node
from app.runs import RunStore, UnknownRun
from app.runtime import UnknownStage, execute_chain, merge_update
from app.standalone import plan_standalone
from app.stages import AGENT_SPECS
from app.trail import record

_UNSET = object()


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
) -> FastAPI:
    """Build the app. `llm` overrides provider resolution (tests inject a fixture or `None`)."""
    app = FastAPI(title="smart-edit console API", version="0.1.0")
    app.state.store = store if store is not None else RunStore(runs_dir)
    app.state.llm = resolve_llm() if llm is _UNSET else llm

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
    async def trigger_stage(thread_id: str, stage: str, template: str | None = None) -> dict:
        """Run a stage chain. `?template=<id>` asks for template-driven audit (design D18).

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

        async with store_.lock(thread_id):
            try:
                execute_chain(
                    state,
                    list(plan["chain"]),
                    llm=app.state.llm,
                    template_reference={"template_id": template} if template else None,
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
                events = append_event(
                    state.get("dispositions") or [],
                    finding_id=finding_id,
                    disposition=disposition if isinstance(disposition, str) else "",
                    actor=actor if isinstance(actor, str) else "",
                    severity=finding.get("severity"),
                    reason=reason if isinstance(reason, str) else None,
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
            "latest": latest(events, finding_id),
        }

    @app.get("/runs/{thread_id}")
    async def read_run(thread_id: str) -> dict:
        return to_envelope(app.state.store.get(thread_id))

    return app


app = create_app()