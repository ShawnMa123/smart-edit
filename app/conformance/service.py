"""Template-conformance audit service: pin the draft, run both layers, persist the report.

Flow (per review):

1. resolve the server draft and refuse a stale pin (`draft_id` / revision / sha);
2. read the draft's top-level blocks (same indices the editor uses, so a finding can jump);
3. deterministic layer: extraction profile -> required-field presence (never the model);
4. model layer: redact, call the approved Doubao gateway with the config requirements, validate;
5. aggregate counts/outcome/limitations and store the report.

The service never raises out of the background task: a failed run is a failed run with a code, and
an unavailable model is `unable_to_assess` — never a clean pass.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import FieldsConfigError, load_fields_config
from app.conformance.compose import (
    ComposeError,
    ComposedResult,
    Composition,
    ConformanceComposer,
    PROMPT_VERSION,
    merge_compositions,
)
from app.conformance.config import ConfigError, ConformanceConfig, get_config, load_configs
from app.conformance.contracts import (
    ConfigDetail,
    ConfigSummary,
    ConformanceRequest,
    Counts,
    MissingField,
    Provenance,
    RedactionInfo,
    RedactionStep,
    Report,
    RequirementDetail,
    RequirementResult,
    Run,
    SnapshotInfo,
)
from app.conformance.redact import RedactionOutcome, mode_from_env, redact_blocks
from app.conformance.store import ConformanceStore
from app.documents.projection import project_document
from app.nodes.extract import extract_node
from app.nodes.normalize import normalize_node
from app.parsing.extraction_profile import ProfileError, load_profile_by_id

SUMMARY_NOTE = (
    "The summary is model-written. 'Pass' means the quoted text meets that requirement; it is not "
    "a statement that the document is compliant."
)
_BLOCK_ID = re.compile(r"^b\d+$")
_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class Settings:
    timeout: float = 60.0
    coverage_ratio: float = 0.6
    redaction: str = "basic"
    language: str = "auto"

    @classmethod
    def from_env(cls) -> "Settings":
        def _float(name: str, default: float) -> float:
            raw = (os.environ.get(name) or "").strip()
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            timeout=_float("SMART_EDIT_CONFORMANCE_TIMEOUT", 60.0),
            coverage_ratio=_float("SMART_EDIT_CONFORMANCE_RATIO", 0.6),
            redaction=mode_from_env(),
            language=(os.environ.get("SMART_EDIT_CONFORMANCE_LANGUAGE") or "auto").strip() or "auto",
        )


class ConformanceError(RuntimeError):
    """A refusal the HTTP layer can express as `status` + `code`."""

    def __init__(self, status: int, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def language_for(text: str, requested: str | None) -> str:
    """`auto` follows the document; an explicit request wins."""
    clean = (requested or "").strip()
    if clean and clean != "auto":
        return clean
    return "zh-CN" if _CJK.search(text or "") else "en"


def _summary_of(config: ConformanceConfig) -> ConfigSummary:
    return ConfigSummary(
        config_id=config.config_id,
        version=config.version,
        name=config.name,
        document_types=list(config.document_types),
        language=config.language,
        description=config.description,
        requirement_count=len(config.requirements),
        required_fields=list(config.required_fields),
        content_sha256=config.content_sha256,
    )


def _unable_composition(config: ConformanceConfig, code: str) -> Composition:
    """One failed chunk: every requirement is `unable_to_assess`, never silently "passed"."""
    return Composition(
        summary="",
        results=tuple(
            ComposedResult(
                id=requirement.id,
                status="unable_to_assess",
                explanation="This chunk was not assessed.",
                confidence="low",
                reason_codes=(code,),
            )
            for requirement in config.requirements
        ),
        notes=(),
        model=None,
        calls=0,
    )


class ConformanceService:
    """One review = one run + one report, both persisted."""

    def __init__(
        self,
        *,
        documents: Any = None,
        composer: ConformanceComposer | None = None,
        store: ConformanceStore | None = None,
        settings: Settings | None = None,
        config_dir: str | None = None,
        fields_config: dict[str, dict] | None = None,
    ) -> None:
        self.documents = documents
        self.composer = composer
        self.store = store or ConformanceStore(":memory:")
        self.settings = settings or Settings.from_env()
        self.config_dir = config_dir
        self._fields_config: dict[str, dict] | None = fields_config

    # --- catalog ----------------------------------------------------------------------------
    def list_configs(self) -> list[ConfigSummary]:
        return [_summary_of(config) for config in load_configs(self.config_dir)]

    def config(self, config_id: str) -> ConformanceConfig:
        try:
            return get_config(config_id, self.config_dir)
        except ConfigError as exc:
            raise ConformanceError(400, "unknown_config", str(exc)) from exc

    def config_detail(self, config_id: str) -> ConfigDetail:
        """Read-only inspector view: the requirements the model will be asked to judge."""
        config = self.config(config_id)
        return ConfigDetail(
            config_id=config.config_id,
            version=config.version,
            name=config.name,
            document_types=list(config.document_types),
            language=config.language,
            description=config.description,
            extraction_profile=config.extraction_profile,
            requirement_count=len(config.requirements),
            required_fields=list(config.required_fields),
            content_sha256=config.content_sha256,
            generation=vars(config.generation),
            requirements=[
                RequirementDetail(
                    id=requirement.id,
                    title=requirement.title,
                    level=requirement.level,
                    check=requirement.check,
                    evidence_hint=requirement.evidence_hint,
                    suggestion=requirement.suggestion,
                )
                for requirement in config.requirements
            ],
        )

    # --- lifecycle --------------------------------------------------------------------------
    def submit(
        self,
        request: ConformanceRequest,
        *,
        principal: Any = None,
        idempotency_key: str | None = None,
    ) -> tuple[Run, bool]:
        """Return `(run, needs_background_run)`; a repeated key returns the original run."""
        if principal is not None and principal.workspace_id != request.workspace_id:
            raise ConformanceError(
                403, "workspace_mismatch", "the request workspace does not match the session"
            )
        config = self.config(request.config_id)
        if self.documents is None:
            raise ConformanceError(
                409,
                "document_host_unavailable",
                "this server has no document host, so the draft cannot be read",
            )

        if idempotency_key:
            existing = self.store.get_by_key(idempotency_key)
            if existing is not None:
                return existing, False

        now = _utcnow()
        run = Run(
            run_id=f"cfr_{uuid.uuid4().hex[:12]}",
            status="queued",
            stage="queued",
            created_at=_iso(now),
            report_id=f"crp_{uuid.uuid4().hex[:12]}",
            progress={
                "stage": "queued",
                "planned": len(config.requirements) + len(config.required_fields),
                "done": 0,
                "config_id": config.config_id,
                "config_version": config.version,
            },
        )
        self.store.save_run(run, workspace_id=request.workspace_id, document_id=request.document_id)
        if idempotency_key:
            bound = self.store.remember(idempotency_key, run.run_id)
            if bound is not None and bound.run_id != run.run_id:
                return bound, False
        return run, True

    def execute(self, run_id: str, request: ConformanceRequest, principal: Any = None) -> None:
        """Background task: never raises; every failure is persisted on the run."""
        run = self.store.get_run(run_id)
        if run is None:
            return
        started = time.monotonic()
        try:
            config = self.config(request.config_id)
            planned = len(config.requirements) + len(config.required_fields)
            self._save_run(run, request, status="running", stage="snapshot", progress={"done": 0})
            snapshot = self._snapshot(principal or _principal_for(request), request)
            blocks = self._blocks(snapshot)
            text = "\n\n".join(block["text"] for block in blocks)
            total_chars = sum(len(block["text"]) for block in blocks)
            self._save_run(run, request, status="running", stage="deterministic")
            fields, extraction_status, extraction_profile = self._deterministic(
                text, blocks, config
            )
            self._save_run(
                run,
                request,
                status="running",
                stage="model",
                progress={"done": len(config.required_fields)},
            )

            missing, known_fields = self._missing_fields(fields, config, extraction_status)
            chunks, truncated = self._plan_chunks(blocks, config.generation)
            outcomes, redaction = self._redact_chunks(chunks)
            composition, compose_code, compose_failures = self._compose(
                config=config,
                outcomes=outcomes,
                known_fields=known_fields,
                language=language_for(text, request.language),
                snapshot=snapshot,
                truncated=truncated,
            )
            report = self._report(
                run=run,
                config=config,
                request=request,
                snapshot=snapshot,
                total_chars=total_chars,
                analyzed_chars=sum(
                    len(block["text"]) for outcome in outcomes for block in outcome.blocks
                ),
                truncated=truncated,
                chunk_count=len(chunks),
                missing=missing,
                composition=composition,
                compose_code=compose_code,
                compose_failures=compose_failures,
                redaction=redaction,
                extraction_status=extraction_status,
                extraction_profile=extraction_profile,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            self.store.save_report(
                report, workspace_id=request.workspace_id, document_id=request.document_id
            )
            self._save_run(
                run,
                request,
                status="succeeded",
                stage="done",
                finished=True,
                progress={
                    "stage": "done",
                    "done": planned,
                    "planned": planned,
                    "outcome": report.outcome,
                },
            )
        except ConformanceError as exc:
            self._fail(run, request, exc.code)
        except Exception as exc:  # noqa: BLE001 - a review crash is a failed review
            self._fail(run, request, f"review_error:{type(exc).__name__}")

    def get_run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run is None:
            raise ConformanceError(404, "run_not_found", "conformance run not found")
        return run

    def get_report(self, report_id: str) -> Report:
        report = self.store.get_report(report_id)
        if report is None:
            raise ConformanceError(404, "report_not_found", "conformance report not found")
        return report

    def report_workspace(self, report_id: str) -> str | None:
        return self.store.report_workspace(report_id)

    # --- internals --------------------------------------------------------------------------
    def _save_run(
        self,
        run: Run,
        request: ConformanceRequest,
        *,
        status: str | None = None,
        stage: str | None = None,
        finished: bool = False,
        progress: dict | None = None,
        error: str | None = None,
    ) -> Run:
        current = self.store.get_run(run.run_id) or run
        update: dict[str, Any] = {}
        if status:
            update["status"] = status
        if stage:
            update["stage"] = stage
        if progress is not None or stage:
            merged = dict(current.progress)
            if stage:
                merged["stage"] = stage
            if progress:
                merged.update(progress)
            update["progress"] = merged
        if finished:
            update["finished_at"] = _iso(_utcnow())
        if error:
            update["error"] = error
        updated = current.model_copy(update=update)
        self.store.save_run(
            updated, workspace_id=request.workspace_id, document_id=request.document_id
        )
        return updated

    def _fail(self, run: Run, request: ConformanceRequest, code: str) -> None:
        self._save_run(run, request, status="failed", stage="failed", finished=True, error=code)

    def _snapshot(self, principal: Any, request: ConformanceRequest) -> dict:
        """Read the server draft and refuse a stale pin (never audit an older revision silently)."""
        if self.documents is None:
            raise ConformanceError(
                409, "document_host_unavailable", "this server has no document host"
            )
        try:
            view = self.documents.document_view(principal, request.document_id)
        except Exception as exc:  # noqa: BLE001 - HostError carries its own status/code
            status = int(getattr(exc, "status", 404) or 404)
            code = str(getattr(exc, "code", "document_unavailable") or "document_unavailable")
            raise ConformanceError(status, code, str(exc)) from exc
        if request.draft_id and view.get("draft_id") != request.draft_id:
            raise ConformanceError(
                409,
                "stale_snapshot",
                "the draft changed since this review was requested",
                {"revision": view.get("revision")},
            )
        if request.expected_revision is not None and int(view.get("revision") or 0) != int(
            request.expected_revision
        ):
            raise ConformanceError(
                409,
                "stale_snapshot",
                "the draft changed since this review was requested",
                {"revision": view.get("revision")},
            )
        expected = (request.expected_content_sha256 or "").strip()
        if expected and str(view.get("content_sha256") or "") != expected:
            raise ConformanceError(
                409,
                "stale_snapshot",
                "the draft content changed since this review was requested",
                {"revision": view.get("revision")},
            )
        return view

    def _blocks(self, view: dict) -> list[dict]:
        """Top-level blocks with the editor's own indices (no truncation here)."""
        content = view.get("content")
        projection = project_document(content if isinstance(content, dict) else None)
        blocks: list[dict] = []
        for node in projection.blocks:
            if not _BLOCK_ID.match(node.node_id):
                continue
            text = projection.text[node.start_cp : node.end_cp].strip()
            blocks.append({"i": int(node.node_id[1:]), "text": text})
        blocks.sort(key=lambda item: item["i"])
        if not blocks:
            raw = str(view.get("text") or "")
            blocks = [
                {"i": index, "text": part.strip()}
                for index, part in enumerate(raw.split("\n\n"))
                if part.strip()
            ]
        return blocks

    def _plan_chunks(
        self, blocks: list[dict], generation
    ) -> tuple[list[list[dict]], bool]:
        """Split blocks into chunks; the total sent never exceeds `max_document_chars`.

        Returns `(chunks, truncated)`. A block longer than `chunk_chars` is sliced but keeps its
        block index, so a quote still points at the editor's top-level block.
        """
        total_budget = generation.max_document_chars
        chunk_limit = generation.chunk_chars
        chunks: list[list[dict]] = []
        current: list[dict] = []
        current_chars = 0
        sent = 0
        truncated = False

        for block in blocks:
            text = block["text"]
            if not text:
                continue
            if len(text) <= chunk_limit:
                pieces = [text]
            else:
                pieces = [
                    text[start : start + chunk_limit]
                    for start in range(0, len(text), chunk_limit)
                ]
            for index, piece in enumerate(pieces):
                cost = len(piece) + 2
                if sent + cost > total_budget:
                    truncated = True
                    break
                if current and current_chars + cost > chunk_limit:
                    chunks.append(current)
                    current = []
                    current_chars = 0
                entry: dict[str, Any] = {"i": block["i"], "text": piece}
                if len(pieces) > 1:
                    entry["slice"] = index
                current.append(entry)
                current_chars += cost
                sent += cost
            if truncated:
                break
        if current:
            chunks.append(current)
        return chunks, truncated

    def _field_definitions(self) -> dict[str, dict]:
        if self._fields_config is None:
            try:
                self._fields_config = load_fields_config()
            except FieldsConfigError:
                self._fields_config = {}
        return self._fields_config

    def _deterministic(
        self, text: str, blocks: list[dict], config: ConformanceConfig
    ) -> tuple[dict[str, Any], str, str | None]:
        """Required-field presence from the extraction profile, without a model.

        `not_run` / `failed` is a first-class answer: the report then claims no missing field at all
        rather than guessing one.
        """
        if not config.required_fields or not config.extraction_profile:
            return {}, "not_run", None
        try:
            profile = load_profile_by_id(config.extraction_profile)
        except (ProfileError, Exception):  # noqa: BLE001 - an unusable profile is not a crash
            return {}, "failed", config.extraction_profile

        docs = [
            {
                "file_id": "doc",
                "full_text": text,
                "blocks": [{"text": block["text"], "page": None} for block in blocks],
                "pages": 1,
            }
        ]
        state: dict[str, Any] = {"docs": docs, "trail": [], "stages": [], "_candidates": []}
        try:
            state.update(
                extract_node(
                    state, llm=None, field_keys=list(config.required_fields), profile=profile
                )
            )
            normalized = normalize_node(state)
        except Exception:  # noqa: BLE001 - an extraction crash must not fake a verdict
            return {}, "failed", config.extraction_profile
        return dict(normalized.get("fields") or {}), "deterministic", config.extraction_profile

    def _missing_fields(
        self, fields: dict[str, Any], config: ConformanceConfig, extraction_status: str
    ) -> tuple[list[MissingField], dict[str, Any]]:
        """Missing required fields and the values the model may use as context."""
        missing: list[MissingField] = []
        known_fields: dict[str, Any] = {}
        if extraction_status != "deterministic":
            return missing, known_fields
        definitions = self._field_definitions()
        for key in config.required_fields:
            field = fields.get(key) or {}
            value = field.get("value")
            status = str(field.get("status") or "missing")
            if value not in (None, "") and status in ("extracted", "inferred"):
                known_fields[key] = value
                continue
            definition = definitions.get(key) or {}
            missing.append(
                MissingField(
                    key=key,
                    label=str(definition.get("label") or field.get("label") or key),
                    note="Not found in this revision of the document.",
                )
            )
        return missing, known_fields

    def _redact_chunks(
        self, chunks: list[list[dict]]
    ) -> tuple[list[RedactionOutcome], RedactionInfo]:
        """Redact each chunk separately and aggregate the steps for the report."""
        outcomes = [redact_blocks(chunk, mode=self.settings.redaction) for chunk in chunks]
        totals: dict[str, tuple[int, str]] = {}
        note = ""
        for outcome in outcomes:
            if not note and outcome.note:
                note = outcome.note
            for step in outcome.steps:
                count, sample = totals.get(step.kind, (0, step.sample))
                totals[step.kind] = (count + step.count, sample)
        steps = [
            RedactionStep(kind=kind, count=count, sample=sample)
            for kind, (count, sample) in totals.items()
        ]
        total = sum(step.count for step in steps)
        return outcomes, RedactionInfo(
            applied=total > 0, total=total, note=note, steps=steps
        )

    def _compose(
        self,
        *,
        config: ConformanceConfig,
        outcomes: list[RedactionOutcome],
        known_fields: dict[str, Any],
        language: str,
        snapshot: dict,
        truncated: bool,
    ) -> tuple[Composition | None, str | None, list[tuple[int, str]]]:
        """One model call per chunk, merged with `finding > pass > unable`."""
        if not outcomes:
            return None, "no_document_text", []
        if self.composer is None:
            return None, "composer_unavailable", []
        if not self.composer.available:
            # One clear limitation instead of one per chunk; no chunk is sent at all.
            return None, "composer_unavailable", []
        chunks = [outcome.blocks for outcome in outcomes]
        total = len(chunks)
        compositions: list[Composition] = []
        failures: list[tuple[int, str]] = []
        for index, blocks in enumerate(chunks, start=1):
            try:
                compositions.append(
                    self.composer.review(
                        config=config,
                        blocks=blocks,
                        known_fields=known_fields,
                        language=language,
                        document={
                            "revision": snapshot.get("revision"),
                            "content_sha256": snapshot.get("content_sha256"),
                            "truncated": truncated,
                            "chunk_index": index,
                            "chunk_count": total,
                        },
                    )
                )
            except ComposeError as exc:
                failures.append((index, exc.code))
                compositions.append(_unable_composition(config, exc.code))
            except Exception as exc:  # noqa: BLE001 - a chunk crash is a failed chunk
                code = f"compose_error:{type(exc).__name__}"
                failures.append((index, code))
                compositions.append(_unable_composition(config, code))
        try:
            return merge_compositions(compositions), None, failures
        except ComposeError as exc:
            return None, exc.code, failures

    def _report(
        self,
        *,
        run: Run,
        config: ConformanceConfig,
        request: ConformanceRequest,
        snapshot: dict,
        total_chars: int,
        analyzed_chars: int,
        truncated: bool,
        chunk_count: int,
        missing: list[MissingField],
        composition: Composition | None,
        compose_code: str | None,
        compose_failures: list[tuple[int, str]],
        redaction: RedactionInfo,
        extraction_status: str,
        extraction_profile: str | None,
        elapsed_ms: int,
    ) -> Report:
        limitations: list[dict] = []
        if chunk_count > 1:
            limitations.append(
                {
                    "code": "document_chunked",
                    "message": (
                        f"The document was judged in {chunk_count} chunks; a finding in any chunk "
                        "wins over a pass in another, and a requirement no chunk could show stays "
                        "unable to assess."
                    ),
                }
            )
        if truncated:
            limitations.append(
                {
                    "code": "document_truncated",
                    "message": (
                        f"Only {analyzed_chars} of {total_chars} characters were sent; the rest of "
                        "the document was not assessed."
                    ),
                }
            )
        if extraction_status == "not_run" and config.required_fields:
            limitations.append(
                {
                    "code": "extraction_not_run",
                    "message": (
                        "No extraction profile ran, so missing required fields are not reported. "
                        f"Configure extraction_profile (currently {config.extraction_profile!r})."
                    ),
                }
            )
        elif extraction_status == "failed":
            limitations.append(
                {
                    "code": "extraction_failed",
                    "message": (
                        f"Extraction profile {config.extraction_profile!r} could not run, so missing "
                        "required fields are not reported."
                    ),
                }
            )

        if compose_code:
            limitations.append(
                {
                    "code": compose_code,
                    "message": (
                        "The config requirements were not assessed by the model; no conformance "
                        "claim is made for them."
                    ),
                }
            )
        for index, code in compose_failures:
            limitations.append(
                {
                    "code": f"chunk_{index}_failed",
                    "message": (
                        f"Chunk {index} of {chunk_count} could not be judged ({code}); its "
                        "requirements are reported as unable to assess."
                    ),
                }
            )
        for note in composition.notes if composition else ():
            limitations.append({"code": "model_note", "message": note})

        results: list[RequirementResult] = []
        composed_by_id = {item.id: item for item in (composition.results if composition else ())}
        for requirement in config.requirements:
            severity = "Warning" if requirement.level == "must" else "Info"
            gate = "human_review" if requirement.level == "must" else "advisory"
            composed = composed_by_id.get(requirement.id)
            if composed is None:
                results.append(
                    RequirementResult(
                        id=requirement.id,
                        title=requirement.title,
                        level=requirement.level,
                        status="unable_to_assess",
                        severity=severity,
                        gate_type=gate,
                        explanation="This requirement was not assessed.",
                        suggestion=requirement.suggestion,
                        confidence="low",
                        reason_codes=[compose_code or "not_assessed"],
                    )
                )
                continue
            results.append(
                RequirementResult(
                    id=requirement.id,
                    title=requirement.title,
                    level=requirement.level,
                    status=composed.status,  # type: ignore[arg-type]
                    severity=severity,  # type: ignore[arg-type]
                    gate_type=gate,  # type: ignore[arg-type]
                    explanation=composed.explanation,
                    suggestion=composed.suggestion or requirement.suggestion,
                    quote=composed.quote,
                    block_index=composed.block_index,
                    confidence=composed.confidence,  # type: ignore[arg-type]
                    reason_codes=list(composed.reason_codes),
                )
            )

        passed = sum(1 for item in results if item.status == "pass")
        findings = sum(1 for item in results if item.status == "finding")
        unable = sum(1 for item in results if item.status == "unable_to_assess")
        planned = len(config.requirements)
        counts = Counts(
            requirements=planned,
            passed=passed,
            findings=findings,
            unable_to_assess=unable,
            missing_fields=len(missing),
            coverage_ratio=round((passed + findings) / planned, 3) if planned else 0.0,
        )

        if findings:
            outcome = "findings_present"
        elif missing:
            outcome = "needs_input"
        elif planned and unable:
            outcome = "unable_to_assess"
        else:
            outcome = "no_findings"

        deterministic_ok = not config.required_fields or extraction_status == "deterministic"
        completion = "complete" if deterministic_ok and unable == 0 and not truncated else "partial"

        summary = (composition.summary if composition else "") or (
            f"Checked {planned} requirement(s): {passed} pass, {findings} finding, {unable} unable "
            f"to assess; {len(missing)} required field(s) missing."
        )

        model_label = (
            composition.model
            if composition is not None
            else (self.composer.label() if self.composer else None)
        )
        return Report(
            report_id=run.report_id or "",
            run_id=run.run_id,
            outcome=outcome,
            completion=completion,
            config=_summary_of(config),
            snapshot=SnapshotInfo(
                document_id=str(snapshot.get("document_id") or request.document_id),
                draft_id=snapshot.get("draft_id"),
                title=snapshot.get("title"),
                revision=snapshot.get("revision"),
                content_sha256=snapshot.get("content_sha256"),
                analyzed_chars=analyzed_chars,
                truncated=truncated,
            ),
            summary=summary,
            summary_note=SUMMARY_NOTE,
            results=results,
            missing_fields=missing,
            counts=counts,
            limitations=limitations,
            provenance=Provenance(
                model=model_label,
                prompt_version=PROMPT_VERSION,
                config_sha256=config.content_sha256,
                extraction_status=extraction_status,  # type: ignore[arg-type]
                extraction_profile=extraction_profile,
                model_calls=composition.calls if composition is not None else 0,
                duration_ms=elapsed_ms,
                redaction=redaction,
            ),
        )


def _principal_for(request: ConformanceRequest) -> Any:
    """Fallback for bare-router tests; the real app always passes the session principal."""
    from app.shared.ports import Principal

    return Principal(user_id="system", workspace_id=request.workspace_id)


__all__ = [
    "ConformanceError",
    "ConformanceService",
    "SUMMARY_NOTE",
    "Settings",
    "language_for",
]