"""FastAPI application for one run's transport.

Spec: `openspec/changes/frontend-console/specs/console-api/spec.md`
Design: `openspec/changes/frontend-console/design.md` D1, D3, D5, D7.

Three endpoints only: create a run, trigger a stage, read a run. `HITL` / `resume` / `events` belong
to `poc-skeleton` §8-§9 once the graph exists.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.envelope import to_envelope
from app.api.errors import ApiFailure, IncompleteResult, error_body
from app.llm import resolve_llm
from app.runs import RunStore, UnknownRun
from app.runtime import UnknownStage, execute_chain
from app.standalone import plan_standalone
from app.stages import AGENT_SPECS

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

    @app.get("/runs/{thread_id}")
    async def read_run(thread_id: str) -> dict:
        return to_envelope(app.state.store.get(thread_id))

    return app


app = create_app()