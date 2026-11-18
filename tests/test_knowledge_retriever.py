"""Task 2.4 — lexical retrieval baseline, ACL/effective filtering and failure distinction."""

from __future__ import annotations

import pytest

from app.assistant.domain.query import analyze
from app.assistant.eval import load_cases
from app.assistant.ports import Principal
from app.assistant.store import SQLiteStore
from app.knowledge.models import DEFAULT_ALLOWED_SCOPES
from app.knowledge.retriever import LexicalRetriever
from app.knowledge.service import KnowledgeService
from tests.assistant_helpers import WORKSPACE, make_store

PRINCIPAL = Principal(user_id="user_a", workspace_id=WORKSPACE)


def _import(service: KnowledgeService, *, scope: str, effective_from=None, effective_to=None):
    payload = {
        "title": "合成检索测试手册",
        "version_label": "v1",
        "version_id": f"KV-SCOPE-{scope}-{effective_from or 'open'}",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": {
            "source_id": f"KS-SCOPE-{scope}-{effective_from or 'open'}",
            "source_type": "product_manual",
            "publisher": "Synthetic Test",
            "version_label": "v1",
            "scope": scope,
            "synthetic": True,
            "jurisdictions": [],
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        "chunks": [
            {
                "chunk_id": f"KC-{scope}-1",
                "section": "提交",
                "title_path": "测试 / 提交",
                "text": "提交成功后释放编辑锁。本段是合成演示文本。",
                "locator": {"section": "提交"},
            }
        ],
    }
    version = service.import_document(payload, submitted_by="user_author")
    service.review(version["version_id"], "publish", "user_reviewer", "ok")
    return version


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def test_thirty_three_synthetic_questions_keep_a_lexical_hit_baseline(store):
    retriever = LexicalRetriever(store)
    rows = []
    for case in load_cases():
        plan = analyze(case["question"])
        candidates = retriever.search(PRINCIPAL, WORKSPACE, plan, None)
        chunk_ids = [candidate.chunk_id for candidate in candidates]
        expected = case["expected_chunk"]
        rows.append((case["id"], expected is None or expected in chunk_ids, chunk_ids[:3]))

    hits = sum(1 for _, hit, _ in rows if hit)
    assert hits / len(rows) >= 0.9, [row for row in rows if not row[1]]
    assert len(rows) == 33


def test_help_source_is_only_used_for_capability_help(store):
    retriever = LexicalRetriever(store)
    help_plan = analyze("你能做什么？")
    assert help_plan.capability_help is True
    help_results = retriever.search(PRINCIPAL, WORKSPACE, help_plan, None)
    assert help_results
    assert {candidate.source_id for candidate in help_results} == {"KS-HELP-001"}

    normal_plan = analyze("提交版本后编辑锁会释放吗？")
    assert normal_plan.capability_help is False
    normal_results = retriever.search(PRINCIPAL, WORKSPACE, normal_plan, None)
    assert normal_results
    assert all(candidate.source_id != "KS-HELP-001" for candidate in normal_results)


def test_english_questions_use_only_english_sources(store):
    retriever = LexicalRetriever(store)

    help_plan = analyze("What can you do?")
    assert help_plan.capability_help is True
    assert help_plan.help_source_id == "KS-HELP-002"
    help_results = retriever.search(PRINCIPAL, WORKSPACE, help_plan, None)
    assert help_results
    assert {candidate.source_id for candidate in help_results} == {"KS-HELP-002"}
    assert all(candidate.source_type == "product_manual" for candidate in help_results)

    product_plan = analyze("What documents are required for the application?")
    assert product_plan.intent == "product_faq"
    product_results = retriever.search(PRINCIPAL, WORKSPACE, product_plan, None)
    assert product_results
    assert all(candidate.source_id.endswith("-EN") for candidate in product_results)
    assert "KS-PRODUCT-001-EN" in {candidate.source_id for candidate in product_results}

    rule_plan = analyze("What does URDG 758 article 20 require for claims?")
    assert rule_plan.intent == "trade_rule_explanation"
    rule_results = retriever.search(PRINCIPAL, WORKSPACE, rule_plan, None)
    assert rule_results
    assert all(candidate.source_id.endswith("-EN") for candidate in rule_results)
    assert "KS-RULES-001-EN" in {candidate.source_id for candidate in rule_results}


def test_english_definition_question_retrieves_the_guarantee_definition(store):
    retriever = LexicalRetriever(store)
    candidates = retriever.search(
        PRINCIPAL, WORKSPACE, analyze("what is guarantee"), None
    )
    assert candidates
    assert candidates[0].chunk_id == "KC-RULES-001-EN-13"
    assert "written undertaking by a guarantor" in candidates[0].excerpt


def test_chinese_definition_question_retrieves_the_guarantee_definition(store):
    retriever = LexicalRetriever(store)
    candidates = retriever.search(
        PRINCIPAL, WORKSPACE, analyze("国际贸易里的guarantee是什么？"), None
    )
    assert candidates
    assert candidates[0].chunk_id == "KC-RULES-001-13"


def test_chinese_questions_do_not_mix_english_sources(store):
    retriever = LexicalRetriever(store)
    candidates = retriever.search(
        PRINCIPAL, WORKSPACE, analyze("提交版本后编辑锁会释放吗？"), None
    )
    assert candidates
    assert all(candidate.source_id in {
        "KS-PRODUCT-001",
        "KS-RULES-001",
        "KS-POLICY-001",
        "KS-HELP-001",
    } for candidate in candidates)


def test_no_match_is_an_empty_result_not_an_error(store):
    retriever = LexicalRetriever(store)
    candidates = retriever.search(
        PRINCIPAL, WORKSPACE, analyze("quantum entanglement banana"), None
    )
    assert candidates == []


def test_retrieval_dependency_failure_is_not_masqueraded_as_no_evidence(tmp_path):
    class Broken:
        def published_chunks(self, *args, **kwargs):
            raise RuntimeError("retrieval dependency unavailable")

    retriever = LexicalRetriever(Broken())
    with pytest.raises(RuntimeError):
        retriever.search(PRINCIPAL, WORKSPACE, analyze("提交版本后编辑锁会释放吗"), None)


def test_scope_outside_the_acl_is_filtered_before_scoring(tmp_path):
    store = SQLiteStore(tmp_path / "k.db")
    service = KnowledgeService(store)
    _import(service, scope="restricted_other_tenant")

    assert store.published_chunks(allowed_scopes=DEFAULT_ALLOWED_SCOPES) == []
    assert retriever_ids(store) == []
    # The admin can still see it when explicitly allowed; the default never widens.
    assert len(store.published_chunks(allowed_scopes=("restricted_other_tenant",))) == 1


def test_expired_versions_are_excluded_and_historical_dates_select_the_old_version(tmp_path):
    store = SQLiteStore(tmp_path / "k.db")
    service = KnowledgeService(store)
    _import(service, scope="organization", effective_from="2022-01-01", effective_to="2024-01-01")

    assert store.published_chunks("2023-06-01", allowed_scopes=DEFAULT_ALLOWED_SCOPES)
    assert store.published_chunks("2026-01-01", allowed_scopes=DEFAULT_ALLOWED_SCOPES) == []


def retriever_ids(store: SQLiteStore) -> list[str]:
    retriever = LexicalRetriever(store)
    candidates = retriever.search(
        PRINCIPAL, WORKSPACE, analyze("提交版本后编辑锁会释放吗"), None
    )
    return [candidate.chunk_id for candidate in candidates]