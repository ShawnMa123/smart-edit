"""Build the A services with local adapters (design D2). C swaps this factory."""

from __future__ import annotations

import os
from pathlib import Path

from app.assistant.adapters import (
    AssistantServices,
    FakeAuthorization,
    FakeIdentity,
    FakeSnapshots,
    StoreAudit,
    SystemClock,
    assert_safe_mode,
    resolve_mode,
)
from app.assistant.egress import EgressPolicy
from app.assistant.gateway import DoubaoGateway
from app.assistant.pipeline import FixtureComposer
from app.assistant.retrieval import FixtureWebSearch, HttpWebSearch, RagHttpAdapter
from app.assistant.settings import AssistantSettings
from app.assistant.statute import StatuteRetriever
from app.assistant.store import SQLiteStore
from app.knowledge.retriever import LexicalRetriever
from app.knowledge.seed import seed_knowledge
from app.knowledge.service import KnowledgeService
from app.logging_setup import get_logger

DB_ENV = "SMART_EDIT_ASSISTANT_DB"


def build_services(
    *,
    db_path: str | Path | None = None,
    mode: str | None = None,
    seed: bool = True,
    settings: AssistantSettings | None = None,
    retriever: object | None = None,
    web: object | None = None,
    gateway: object | None = None,
    egress: object | None = None,
    statute: object | None = None,
    identity: object | None = None,
    authorization: object | None = None,
    resource_authorization: object | None = None,
    evidence_authorizer: object | None = None,
    activity: object | None = None,
) -> AssistantServices:
    resolved = resolve_mode(mode)
    resolved_settings = settings or AssistantSettings.from_env()
    assert_safe_mode(resolved, resolved_settings)
    store = SQLiteStore(db_path or os.environ.get(DB_ENV, "runs/assistant.db"))
    seed_result = {"imported": 0, "published": 0}
    if seed:
        # Reconcile even when the DB is non-empty: an older local DB must gain new fixture
        # sources/versions (e.g. English corpus, help guide) on restart.
        seed_result = seed_knowledge(store)

    local_retriever = retriever
    if local_retriever is None:
        local_retriever = (
            RagHttpAdapter(
                endpoint=resolved_settings.rag_endpoint or "",
                api_key=resolved_settings.rag_api_key,
            )
            if resolved_settings.rag_endpoint
            else LexicalRetriever(store)
        )

    web_layer = web
    if web_layer is None and resolved_settings.web == "fixture":
        web_layer = FixtureWebSearch()
    elif web_layer is None and resolved_settings.web == "http" and resolved_settings.web_endpoint:
        web_layer = HttpWebSearch(
            endpoint=resolved_settings.web_endpoint, api_key=resolved_settings.web_api_key
        )

    model_gateway = gateway
    if model_gateway is None:
        if resolved_settings.model and resolved_settings.model_name and resolved_settings.api_key:
            model_gateway = DoubaoGateway(
                api_key=resolved_settings.api_key,
                base_url=resolved_settings.base_url,
                model=resolved_settings.model_name,
                thinking=resolved_settings.thinking,
            )
        else:
            model_gateway = FixtureComposer()

    policy = egress or EgressPolicy.load(resolved_settings.egress_policy)

    statute_layer = statute
    if (
        statute_layer is None
        and resolved_settings.statute
        and resolved_settings.statute_base_url
        and resolved_settings.statute_api_token
    ):
        statute_layer = StatuteRetriever(
            base_url=resolved_settings.statute_base_url,
            api_token=resolved_settings.statute_api_token,
            timeout=resolved_settings.statute_timeout,
            chat_timeout=resolved_settings.chat_timeout,
            expansions=getattr(policy, "query_expansion", None),
        )

    logger = get_logger("bootstrap")
    if resolved != "test":
        # Safe to print: labels/booleans only, never keys, tokens or endpoints with credentials.
        logger.info("mode=%s db=%s", resolved, store.path)
        if seed:
            logger.info(
                "knowledge corpus: imported=%d published=%d published_chunks=%d",
                seed_result["imported"],
                seed_result["published"],
                len(store.published_chunks()),
            )
        logger.info(
            "assistant: model=%s approved=%s general_web=%s approved_web=%s web=%s rag=%s "
            "statute=%s egress=%s",
            resolved_settings.processor_label if resolved_settings.model else "fixture",
            resolved_settings.approved_processor,
            bool(resolved_settings.general_web)
            and bool(getattr(model_gateway, "supports_tool_search", False))
            and policy is not None,
            web_layer is not None,
            resolved_settings.web,
            bool(resolved_settings.rag_endpoint),
            statute_layer is not None,
            getattr(policy, "version", "unset"),
        )

    return AssistantServices(
        store=store,
        identity=identity or FakeIdentity(),
        authorization=authorization or FakeAuthorization(),
        snapshots=FakeSnapshots(store),
        audit=StoreAudit(store),
        clock=SystemClock(),
        retriever=local_retriever,
        gateway=model_gateway,
        knowledge_admin=KnowledgeService(store),
        mode=resolved,
        egress=policy,
        web=web_layer,
        settings=resolved_settings,
        statute=statute_layer,
        resource_authorization=resource_authorization,
        evidence_authorizer=evidence_authorizer,
        activity=activity,
        auth_mode=resolved_settings.auth_mode,
    )