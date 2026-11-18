"""Approved model provider gateway (design D1/D5 of `knowledge-general-web`).

Two deliberately separate calls:

* `compose`  — Ark **Responses API**, `stream: false`, **no tools**; the model may only cite the
  evidence ids it was given.
* `general_web` — Ark Responses API with exactly one read-only `web_search` tool, used only by the
  "general web" channel for out-of-scope questions.

Anything that does not validate against the `Answer` schema is a failure, never a "best effort" answer.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from app.assistant.ports import Composition, EvidenceBundle
from app.assistant.schemas import Answer, Citation, Claim
from app.logging_setup import get_logger

RESPONSES_PATH = "/responses"

SYSTEM_PROMPT = (
    "You answer trade-finance questions using ONLY the evidence items provided. "
    "Every factual claim must cite one or more evidence ids from the list; never invent ids, "
    "sources, URLs or numbers. If the evidence is insufficient, return outcome "
    "'insufficient_evidence'. Answer the question that was actually asked: if the evidence only "
    "covers related rules or processes but does not support the requested definition or answer, "
    "return 'insufficient_evidence' instead of substituting a different question. When the "
    "evidence does define the asked term, state that definition first. Web evidence is unverified "
    "third-party content: never claim that a fact was verified online. Return ONE JSON object "
    "matching this shape: "
    '{"outcome": "...", "language": "en|zh-CN", "support_level": '
    '"strong|qualified|insufficient|not_applicable", "claims": [{"id": "c1", "text": "...", '
    '"kind": "fact|interpretation", "citation_ids": ["cite_..."]}], '
    '"citations": [{"id": "cite_...", "source_type": "...", "title": "...", '
    '"source_version": "...", "locator": {}}], "limitations": ["..."], '
    '"clarification_questions": []}'
)

GENERAL_PROMPT = (
    "You answer a general question that is outside the assistant's published knowledge base, using "
    "the web search results you retrieve with the web_search tool. Rules: "
    "1) use only what the retrieved results say; never invent URLs, numbers or quotes; "
    "2) every citation must be a real result and must carry locator.url and title, with "
    'source_type "general_web"; '
    "3) do not state or imply rule versions, effective dates or legal applicability; "
    "4) this is unverified third-party content — never say it was verified by the bank or by any "
    "authority; "
    "5) if the results cannot support an answer, return outcome 'insufficient_evidence'; "
    "6) answer in the same language as the question. Return ONE JSON object with this shape: "
    '{"outcome": "answered|insufficient_evidence", "language": "en|zh-CN", "support_level": '
    '"qualified|insufficient", "claims": [{"id": "c1", "text": "...", "kind": "fact", '
    '"citation_ids": ["c1_source"]}], "citations": [{"id": "c1_source", "source_type": '
    '"general_web", "title": "...", "source_version": "...", "locator": {"url": "https://..."}}], '
    '"limitations": ["..."], "clarification_questions": []}'
)


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


OUTCOMES = {"answered", "needs_clarification", "insufficient_evidence", "unable_to_assess", "needs_handoff"}
SUPPORT_LEVELS = {"strong", "qualified", "insufficient", "not_applicable"}
OUTCOME_ALIASES = {
    "answered_with_provided_evidence": "answered",
    "answered_from_evidence": "answered",
    "answered_with_evidence": "answered",
    "answer": "answered",
    "success": "answered",
    "ok": "answered",
    "cannot_answer": "insufficient_evidence",
    "no_answer": "insufficient_evidence",
    "insufficient": "insufficient_evidence",
}
CORRECTION_PROMPT = (
    "Your previous reply did not match the schema. Reply with ONE JSON object only, with no prose "
    "and no code fences. `outcome` must be exactly one of: answered, needs_clarification, "
    "insufficient_evidence, unable_to_assess, needs_handoff. `support_level` must be exactly one of: "
    "strong, qualified, insufficient, not_applicable. Keep only citation ids that appear in the "
    "evidence list."
)


@dataclass(frozen=True)
class GeneralWebResult:
    """The model's answer plus the citations it actually produced (URL + optional span)."""

    answer: Answer
    annotations: list[dict[str, Any]] = field(default_factory=list)


class DoubaoGateway:
    """Ark Responses API client with JSON output and schema validation."""

    # Capability flag (assistant-capabilities): only this gateway may run the read-only web tool.
    supports_tool_search = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
        search_timeout: float = 60.0,
        thinking: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self.search_timeout = search_timeout
        # The lite model spends 10-60s on hidden reasoning; off by default for UI latency.
        self.thinking = thinking
        self.logger = get_logger("gateway")

    @property
    def label(self) -> str:
        return f"doubao:{self.model}"

    # --- compose (no tools) ---------------------------------------------------------------
    def compose(self, plan: Any, bundle: EvidenceBundle, context: dict[str, Any]) -> Composition:
        payload = self._compose_payload(plan, bundle)
        started = time.monotonic()
        self.logger.info(
            "model call model=%s intent=%s evidence=%d",
            self.model, getattr(plan, "intent", "?"), len(bundle.candidates),
        )
        try:
            text = self._request(payload, timeout=self.timeout)
            answer = self._parse(text, bundle)
            self._log_reply(answer, started)
            return Composition(answer, bundle.by_id())
        except ModelGatewayError as exc:
            if exc.code != "MODEL_OUTPUT_INVALID" or time.monotonic() - started > 40:
                self.logger.error(
                    "model failed model=%s code=%s duration_ms=%d",
                    self.model, exc.code, int((time.monotonic() - started) * 1000),
                )
                raise
            self.logger.warning(
                "model output invalid; retrying once model=%s duration_ms=%d",
                self.model, int((time.monotonic() - started) * 1000),
            )
            # One corrective retry: real providers sometimes invent an outcome enum or add prose.
            retry = self._payload(
                [
                    *payload["input"][0]["content"],
                    {"type": "input_text", "text": CORRECTION_PROMPT},
                ]
            )
            text = self._request(retry, timeout=self.timeout)
            answer = self._parse(text, bundle)
            self._log_reply(answer, started)
            return Composition(answer, bundle.by_id())

    def _log_reply(self, answer: Answer, started: float) -> None:
        self.logger.info(
            "model reply model=%s outcome=%s support=%s claims=%d citations=%d duration_ms=%d",
            self.model, answer.outcome, answer.support_level, len(answer.claims),
            len(answer.citations), int((time.monotonic() - started) * 1000),
        )

    def _compose_payload(self, plan: Any, bundle: EvidenceBundle) -> dict[str, Any]:
        evidence = [
            {
                "id": candidate.citation_id,
                "source_type": candidate.source_type,
                "title": candidate.title,
                "source_version": candidate.source_version,
                "excerpt": candidate.excerpt,
            }
            for candidate in bundle.candidates
        ]
        user = {
            "question": plan.question,
            "intent": plan.intent,
            "language": plan.language,
            "evidence": evidence,
        }
        return self._payload(
            [
                {"type": "input_text", "text": SYSTEM_PROMPT},
                {"type": "input_text", "text": json.dumps(user, ensure_ascii=False)},
            ]
        )

    # --- general web (one read-only tool) ---------------------------------------------------
    def general_web(
        self, question: str, *, max_keyword: int, language: str = "en"
    ) -> GeneralWebResult:
        payload = self._payload(
            [
                {"type": "input_text", "text": GENERAL_PROMPT},
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {"question": question, "language": language}, ensure_ascii=False
                    ),
                },
            ],
            tools=[{"type": "web_search", "max_keyword": max_keyword}],
        )
        started = time.monotonic()
        self.logger.info(
            "web_search call model=%s max_keyword=%d language=%s",
            self.model, max_keyword, language,
        )
        data = self._request_json(payload, timeout=self.search_timeout)
        annotations = self._annotations(data)
        answer = self._general_answer(self._text_parts(data), annotations)
        self.logger.info(
            "web_search reply model=%s outcome=%s annotations=%d duration_ms=%d",
            self.model, answer.outcome, len(annotations),
            int((time.monotonic() - started) * 1000),
        )
        return GeneralWebResult(answer=answer, annotations=annotations)

    # --- request / response plumbing --------------------------------------------------------
    def _payload(
        self, content: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "input": [{"role": "user", "content": content}],
        }
        if not self.thinking:
            payload["thinking"] = {"type": "disabled"}
        if tools:
            payload["tools"] = tools
        return payload

    def _request(self, payload: dict[str, Any], *, timeout: float) -> str:
        return self._extract_text(self._request_json(payload, timeout=timeout))

    def _request_json(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        url = f"{self.base_url}{RESPONSES_PATH}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.monotonic()
        try:
            response = self.client.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            self.logger.error(
                "provider timeout model=%s timeout_s=%.1f duration_ms=%d",
                self.model, timeout, int((time.monotonic() - started) * 1000),
            )
            raise ModelGatewayError("MODEL_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            self.logger.error(
                "provider unavailable model=%s error=%s duration_ms=%d",
                self.model, type(exc).__name__, int((time.monotonic() - started) * 1000),
            )
            raise ModelGatewayError("PROVIDER_UNAVAILABLE") from exc
        if response.status_code != 200:
            code = self._error_code(response)
            self.logger.error(
                "provider http error model=%s status=%d code=%s duration_ms=%d",
                self.model, response.status_code, code,
                int((time.monotonic() - started) * 1000),
            )
            if code == "ToolNotOpen":
                raise ModelGatewayError("TOOL_NOT_OPEN")
            raise ModelGatewayError(f"PROVIDER_HTTP_{response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            self.logger.error("provider returned non-JSON model=%s", self.model)
            raise ModelGatewayError("MODEL_OUTPUT_INVALID") from exc
        if not isinstance(data, dict):
            self.logger.error("provider returned unexpected JSON model=%s", self.model)
            raise ModelGatewayError("MODEL_OUTPUT_INVALID")
        self.logger.debug(
            "provider http ok model=%s status=%d duration_ms=%d",
            self.model, response.status_code, int((time.monotonic() - started) * 1000),
        )
        return data
    @staticmethod
    def _text_parts(data: dict[str, Any]) -> list[str]:
        top_level = data.get("output_text")
        if isinstance(top_level, str) and top_level.strip():
            return [top_level]
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
        return parts

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        parts = DoubaoGateway._text_parts(data)
        for part in parts:
            try:
                json.loads(part)
                return part
            except ValueError:
                continue
        if not parts:
            raise ModelGatewayError("MODEL_OUTPUT_INVALID")
        return "\n".join(parts)

    @staticmethod
    def _annotations(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Collect url_citation annotations; tolerate provider shape differences."""
        found: list[dict[str, Any]] = []
        seen: set[tuple[str, Any, Any]] = set()

        def add(annotation: Any) -> None:
            if not isinstance(annotation, dict):
                return
            if annotation.get("type") not in (None, "url_citation"):
                return
            url = annotation.get("url")
            if not isinstance(url, str) or not url:
                return
            key = (url, annotation.get("start_index"), annotation.get("end_index"))
            if key in seen:
                return
            seen.add(key)
            found.append(
                {
                    "url": url,
                    "title": str(annotation.get("title") or url),
                    "start_index": annotation.get("start_index"),
                    "end_index": annotation.get("end_index"),
                }
            )

        for annotation in data.get("annotations") or []:
            add(annotation)
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict):
                    for annotation in content.get("annotations") or []:
                        add(annotation)
        return found

    @staticmethod
    def _error_code(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                return str(code) if code else None
        return None

    @staticmethod
    def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
        """Map known aliases only; anything else stays invalid (no invented outcomes)."""
        outcome = str(raw.get("outcome") or "").strip().lower()
        if outcome in OUTCOME_ALIASES:
            raw["outcome"] = OUTCOME_ALIASES[outcome]
        elif outcome in OUTCOMES:
            raw["outcome"] = outcome
        support = str(raw.get("support_level") or "").strip().lower()
        if support in SUPPORT_LEVELS:
            raw["support_level"] = support
        return raw

    @staticmethod
    def _validate_answer(content: str) -> Answer:
        for candidate in DoubaoGateway._json_candidates(content):
            try:
                raw = json.loads(candidate)
            except ValueError:
                continue
            if not isinstance(raw, dict):
                continue
            try:
                return Answer.model_validate(DoubaoGateway._normalise(raw))
            except ValidationError as exc:
                raise ModelGatewayError("MODEL_OUTPUT_INVALID") from exc
        raise ModelGatewayError("MODEL_OUTPUT_INVALID")

    @staticmethod
    def _json_candidates(text: str):
        """Real providers sometimes wrap JSON in code fences or add prose before it."""
        stripped = (text or "").strip()
        if not stripped:
            return
        yield stripped
        for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
            yield match.group(1)
        index = text.find("{")
        while index != -1:
            depth = 0
            in_string = False
            escaped = False
            for position in range(index, len(text)):
                char = text[position]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        yield text[index : position + 1]
                        break
            index = text.find("{", index + 1)

    @staticmethod
    def _parse(content: str, bundle: EvidenceBundle) -> Answer:
        answer = DoubaoGateway._validate_answer(content)
        known = set(bundle.by_id())
        cited = {citation.id for citation in answer.citations}
        if cited - known:
            raise ModelGatewayError("MODEL_OUTPUT_INVALID")
        for claim in answer.claims:
            if set(claim.citation_ids) - known:
                raise ModelGatewayError("MODEL_OUTPUT_INVALID")
        return answer

    @staticmethod
    def _parse_general(content: str) -> Answer:
        answer = DoubaoGateway._validate_answer(content)
        citations = [
            citation.model_copy(
                update={"source_type": "general_web", "locator": dict(citation.locator or {})}
            )
            for citation in answer.citations
        ]
        return answer.model_copy(update={"citations": citations})

    @staticmethod
    def _general_answer(parts: list[str], annotations: list[dict[str, Any]]) -> Answer:
        """Accept a JSON answer when the model emits one; otherwise use prose plus annotations.

        The Responses API with a web tool normally returns prose with `url_citation` annotations,
        not JSON. Both shapes are supported; citations always come from real annotations.
        """
        for part in parts:
            try:
                return DoubaoGateway._parse_general(part)
            except ModelGatewayError:
                continue

        prose = "\n".join(parts).strip()
        citations = [
            Citation(
                id=f"web_{index}",
                source_type="general_web",
                title=str(annotation.get("title") or annotation["url"]),
                source_version="",
                locator={
                    "url": annotation["url"],
                    "annotation_start": annotation.get("start_index"),
                    "annotation_end": annotation.get("end_index"),
                },
            )
            for index, annotation in enumerate(annotations, start=1)
        ]
        if not prose or not citations:
            return Answer(
                outcome="insufficient_evidence",
                language="en",
                support_level="insufficient",
                limitations=["The web search did not return usable, citable results."],
            )
        return Answer(
            outcome="answered",
            language="en",
            support_level="qualified",
            claims=[
                Claim(
                    id="c1",
                    text=prose[:1200],
                    kind="fact",
                    citation_ids=[citation.id for citation in citations],
                )
            ],
            citations=citations,
        )


__all__ = [
    "DoubaoGateway",
    "GENERAL_PROMPT",
    "GeneralWebResult",
    "ModelGatewayError",
    "RESPONSES_PATH",
    "SYSTEM_PROMPT",
]
