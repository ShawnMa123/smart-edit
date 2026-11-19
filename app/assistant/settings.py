"""Provider and egress settings for the knowledge assistant.

Design: `openspec/changes/knowledge-assistant-web-rag/design.md` D5/D12.

Nothing here is enabled by default: with no configuration the assistant keeps using the fixture
composer and never performs an outbound request. Invalid values fail at startup instead of being
silently ignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MODEL_ENV = "SMART_EDIT_ASSISTANT_MODEL"
MODEL_API_KEY_ENV = "SMART_EDIT_ASSISTANT_API_KEY"
MODEL_BASE_URL_ENV = "SMART_EDIT_ASSISTANT_BASE_URL"
PROCESSOR_ENV = "SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED"
WEB_ENV = "SMART_EDIT_ASSISTANT_WEB"
WEB_ENDPOINT_ENV = "SMART_EDIT_ASSISTANT_WEB_ENDPOINT"
WEB_API_KEY_ENV = "SMART_EDIT_ASSISTANT_WEB_API_KEY"
RAG_ENDPOINT_ENV = "SMART_EDIT_ASSISTANT_RAG_ENDPOINT"
RAG_API_KEY_ENV = "SMART_EDIT_ASSISTANT_RAG_API_KEY"
EGRESS_POLICY_ENV = "SMART_EDIT_ASSISTANT_EGRESS_POLICY"
# Knowledge presets may live in one JSON file (`knowledge-simple-ask`); this points at it.
KNOWLEDGE_CONFIG_ENV = "SMART_EDIT_KNOWLEDGE_CONFIG"
# Whether the web fallback starts enabled. Deployment policy, not a UI decision.
WEB_DEFAULT_ENV = "SMART_EDIT_ASSISTANT_WEB_DEFAULT"
GENERAL_WEB_ENV = "SMART_EDIT_ASSISTANT_GENERAL_WEB"
WEB_SEARCH_MAX_KEYWORD_ENV = "SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD"
THINKING_ENV = "SMART_EDIT_ASSISTANT_THINKING"
# Statute evidence source (knowledge-statute-retrieval). Off by default: an enabled source without
# an endpoint or a token fails at startup instead of silently returning "no statute evidence".
STATUTE_ENV = "SMART_EDIT_STATUTE"
STATUTE_BASE_URL_ENV = "MERCATORIA_BASE_URL"
STATUTE_TOKEN_ENV = "MERCATORIA_API_TOKEN"
CHAT_TIMEOUT_ENV = "MERCATORIA_CHAT_TIMEOUT"

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
# `None` means "resolve by priority" (`knowledge.json` → `knowledge.sample.json` → `egress.yaml`),
# so an explicit `SMART_EDIT_ASSISTANT_EGRESS_POLICY` still wins but the shipped preset is usable.
DEFAULT_EGRESS_POLICY: str | None = None
MODEL_PREFIX = "doubao:"
WEB_PROVIDERS = ("off", "fixture", "http")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}
# Statute source defaults; the retrieval timeout is deliberately well above the measured ~151 ms.
# `/v1/chat` also runs a server-side LLM, so it needs a much larger budget.
STATUTE_DEFAULT_TIMEOUT = 2.5
CHAT_DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class AssistantSettings:
    """Resolved provider settings; every field defaults to "no external call"."""

    model: str | None = None
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    approved_processor: bool = False
    web: str = "off"
    web_endpoint: str | None = None
    web_api_key: str | None = None
    rag_endpoint: str | None = None
    rag_api_key: str | None = None
    egress_policy: str | None = DEFAULT_EGRESS_POLICY
    # General web channel (knowledge-general-web): a second, explicit opt-in.
    general_web: bool = False
    # Whether the web fallback starts enabled (`knowledge-simple-ask`); default on, user can switch off.
    web_default: bool = True
    web_search_max_keyword: int = 3
    # Hidden reasoning costs 10-60s per call; off unless explicitly enabled.
    thinking: bool = False
    # Statute evidence source (`knowledge-statute-retrieval`): disabled unless explicitly turned on.
    statute: bool = False
    statute_base_url: str | None = None
    statute_api_token: str | None = None
    statute_timeout: float = STATUTE_DEFAULT_TIMEOUT
    chat_timeout: float = CHAT_DEFAULT_TIMEOUT

    @property
    def model_provider(self) -> str | None:
        return self.model.split(":", 1)[0] if self.model else None

    @property
    def model_name(self) -> str | None:
        return self.model.split(":", 1)[1] if self.model and ":" in self.model else None

    @property
    def processor_label(self) -> str:
        return self.model or "fixture"

    @property
    def web_enabled(self) -> bool:
        return self.web in ("fixture", "http")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AssistantSettings":
        values = env if env is not None else os.environ
        raw_model = (values.get(MODEL_ENV) or "").strip()
        if raw_model and not raw_model.startswith(MODEL_PREFIX):
            raise ValueError(
                f"{MODEL_ENV} must be '{MODEL_PREFIX}<model>' or empty; got {raw_model!r}"
            )
        raw_web = (values.get(WEB_ENV) or "off").strip().lower()
        if raw_web not in WEB_PROVIDERS:
            raise ValueError(f"{WEB_ENV} must be one of {WEB_PROVIDERS}; got {raw_web!r}")
        model = raw_model or None
        if model and not (values.get(MODEL_API_KEY_ENV) or "").strip():
            # A configured provider without credentials must fail loudly, not fall back.
            raise ValueError(f"{MODEL_API_KEY_ENV} is required when {MODEL_ENV} is set")
        raw_keywords = (values.get(WEB_SEARCH_MAX_KEYWORD_ENV) or "").strip()
        try:
            max_keyword = int(raw_keywords) if raw_keywords else 3
        except ValueError as exc:
            raise ValueError(
                f"{WEB_SEARCH_MAX_KEYWORD_ENV} must be an integer; got {raw_keywords!r}"
            ) from exc
        max_keyword = max(1, min(5, max_keyword))
        raw_web_default = (values.get(WEB_DEFAULT_ENV) or "").strip().lower()
        if raw_web_default and raw_web_default not in _TRUE and raw_web_default not in _FALSE:
            raise ValueError(f"{WEB_DEFAULT_ENV} must be 'on' or 'off'; got {raw_web_default!r}")
        web_default = True if not raw_web_default else raw_web_default in _TRUE
        raw_statute = (values.get(STATUTE_ENV) or "").strip().lower()
        if raw_statute not in _TRUE and raw_statute not in _FALSE:
            raise ValueError(f"{STATUTE_ENV} must be 'on' or 'off'; got {raw_statute!r}")
        statute_enabled = raw_statute in _TRUE
        statute_base_url = (values.get(STATUTE_BASE_URL_ENV) or "").strip().rstrip("/") or None
        statute_token = (values.get(STATUTE_TOKEN_ENV) or "").strip() or None
        if statute_enabled and not statute_base_url:
            # Fail loudly: an enabled source that cannot be addressed must not read as "no statutes".
            raise ValueError(f"{STATUTE_BASE_URL_ENV} is required when {STATUTE_ENV}=on")
        if statute_enabled and not statute_token:
            raise ValueError(f"{STATUTE_TOKEN_ENV} is required when {STATUTE_ENV}=on")
        raw_chat_timeout = (values.get(CHAT_TIMEOUT_ENV) or "").strip()
        try:
            chat_timeout = float(raw_chat_timeout) if raw_chat_timeout else CHAT_DEFAULT_TIMEOUT
        except ValueError as exc:
            raise ValueError(
                f"{CHAT_TIMEOUT_ENV} must be a number; got {raw_chat_timeout!r}"
            ) from exc
        if chat_timeout <= 0:
            raise ValueError(f"{CHAT_TIMEOUT_ENV} must be greater than 0; got {chat_timeout!r}")
        return cls(
            model=model,
            base_url=(values.get(MODEL_BASE_URL_ENV) or DEFAULT_BASE_URL).strip(),
            api_key=(values.get(MODEL_API_KEY_ENV) or "").strip() or None,
            approved_processor=(values.get(PROCESSOR_ENV) or "").strip().lower() in _TRUE,
            general_web=(values.get(GENERAL_WEB_ENV) or "").strip().lower() in _TRUE,
            web_default=web_default,
            web_search_max_keyword=max_keyword,
            thinking=(values.get(THINKING_ENV) or "").strip().lower() in _TRUE,
            statute=statute_enabled,
            statute_base_url=statute_base_url,
            statute_api_token=statute_token,
            chat_timeout=chat_timeout,
            web=raw_web,
            web_endpoint=(values.get(WEB_ENDPOINT_ENV) or "").strip() or None,
            web_api_key=(values.get(WEB_API_KEY_ENV) or "").strip() or None,
            rag_endpoint=(values.get(RAG_ENDPOINT_ENV) or "").strip() or None,
            rag_api_key=(values.get(RAG_API_KEY_ENV) or "").strip() or None,
            egress_policy=(values.get(KNOWLEDGE_CONFIG_ENV) or values.get(EGRESS_POLICY_ENV) or DEFAULT_EGRESS_POLICY or "").strip() or None,
        )


def assert_production_safe(mode: str, settings: AssistantSettings | None = None) -> None:
    """Production may only start with an approved external processor configured.

    The local identity/snapshot adapters are still fakes, so the gate stays closed unless the
    deployment explicitly declares an approved processor; this preserves the old "fail closed"
    behaviour for every other configuration.
    """
    if mode != "production":
        return
    if settings is None or not settings.model or not settings.approved_processor:
        raise RuntimeError(
            "knowledge assistant has only fake/local adapters in this build; production requires "
            f"{MODEL_ENV} with {PROCESSOR_ENV}=1, or must fail closed"
        )