"""Tasks 2.1-2.3 — knowledge models, import/review/publish/withdraw and the CLI."""

from __future__ import annotations

import json

import pytest

from app.assistant.store import SQLiteStore
from app.knowledge.cli import main
from app.knowledge.models import KnowledgeError, applicability, parse_chunks, parse_source
from app.knowledge.seed import FIXTURES
from app.knowledge.service import KnowledgeService


def _payload(
    *,
    source_id: str = "KS-TEST-001",
    version_label: str = "v1",
    scope: str = "organization",
    jurisdictions: list[str] | None = None,
    effective_from: str | None = "2024-01-01",
    effective_to: str | None = None,
    chunks: list[dict] | None = None,
) -> dict:
    return {
        "title": "合成测试手册（演示用）",
        "version_label": version_label,
        "version_id": f"KV-{source_id}-{version_label}",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": {
            "source_id": source_id,
            "source_type": "product_manual",
            "publisher": "Synthetic Test Publisher",
            "version_label": version_label,
            "language": "zh-CN",
            "scope": scope,
            "license_reference": "synthetic-demo",
            "synthetic": True,
            "jurisdictions": jurisdictions or [],
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        "chunks": chunks
        or [
            {
                "chunk_id": f"KC-{source_id}-1",
                "section": "提交",
                "title_path": "测试 / 提交",
                "text": "提交成功后释放编辑锁。本段是合成演示文本。",
                "locator": {"section": "提交"},
            }
        ],
    }


@pytest.fixture
def service(tmp_path):
    return KnowledgeService(SQLiteStore(tmp_path / "k.db"))


def _retrievable(store: SQLiteStore) -> list[str]:
    return [row["version_id"] for row in store.published_chunks()]


def test_import_stops_at_pending_review_and_is_not_retrievable(service):
    version = service.import_document(_payload(), submitted_by="user_author")

    assert version["status"] == "pending_review"
    assert version["submitted_by"] == "user_author"
    assert version["reviewed_by"] is None
    assert _retrievable(service.store) == []


def test_publish_requires_a_different_reviewer(service):
    version = service.import_document(_payload(), submitted_by="user_author")

    with pytest.raises(KnowledgeError):
        service.review(version["version_id"], "publish", "user_author", "self review")
    assert _retrievable(service.store) == []

    published = service.review(version["version_id"], "publish", "user_reviewer", "checked")
    assert published["status"] == "published"
    assert published["reviewed_by"] == "user_reviewer"
    assert _retrievable(service.store) == [version["version_id"]]


def test_rejection_is_not_retrievable_and_is_terminal(service):
    version = service.import_document(_payload(), submitted_by="user_author")
    rejected = service.review(version["version_id"], "reject", "user_reviewer", "wrong version")

    assert rejected["status"] == "rejected"
    assert _retrievable(service.store) == []
    with pytest.raises(KnowledgeError):
        service.review(version["version_id"], "publish", "user_reviewer", "late publish")


def test_a_partial_import_never_publishes_anything(tmp_path):
    store = SQLiteStore(tmp_path / "k.db")
    service = KnowledgeService(store)
    bad = _payload(
        chunks=[
            {"chunk_id": "KC-1", "text": "第一段有效文本。", "locator": {}},
            {"chunk_id": "KC-2", "text": "", "locator": {}},
        ]
    )
    with pytest.raises(KnowledgeError):
        service.import_document(bad, submitted_by="user_author")

    assert store.list_knowledge_versions_all() == []
    assert _retrievable(store) == []


def test_new_publish_supersedes_the_previous_version(service):
    v1 = service.import_document(_payload(version_label="v1"), submitted_by="user_author")
    service.review(v1["version_id"], "publish", "user_reviewer", "v1")
    v2 = service.import_document(_payload(version_label="v2"), submitted_by="user_author")
    service.review(v2["version_id"], "publish", "user_reviewer", "v2")

    assert service.store.get_knowledge_version(v1["version_id"])["status"] == "superseded"
    assert _retrievable(service.store) == [v2["version_id"]]


def test_withdrawn_version_disappears_immediately(service):
    version = service.import_document(_payload(), submitted_by="user_author")
    service.review(version["version_id"], "publish", "user_reviewer", "ok")

    withdrawn = service.withdraw("KS-TEST-001", version["version_id"], "wrong content", "user_ops")
    assert withdrawn["status"] == "withdrawn"
    assert _retrievable(service.store) == []
    with pytest.raises(KnowledgeError):
        service.withdraw("KS-TEST-001", version["version_id"], "again", "user_ops")


def test_source_withdraw_covers_every_version(service):
    version = service.import_document(_payload(), submitted_by="user_author")
    service.review(version["version_id"], "publish", "user_reviewer", "ok")

    result = service.withdraw("KS-TEST-001", None, "source retired", "user_ops")
    assert result["withdrawn_versions"] == [version["version_id"]]
    assert _retrievable(service.store) == []


# --- 2.1 metadata -----------------------------------------------------------------------------


def test_missing_applicability_metadata_is_null_with_a_reason():
    source = parse_source(
        {"source_id": "KS-X", "source_type": "product_manual", "publisher": "P"}
    )
    metadata = applicability(
        {"version_label": "v1", "effective_from": None, "effective_to": None}, source
    )
    assert metadata["jurisdictions"] is None
    assert metadata["version_label"] == "v1"
    reasons = " ".join(metadata["missing"])
    assert "jurisdictions" in reasons and "effective_range" in reasons


def test_metadata_that_exists_is_returned_unchanged():
    source = parse_source(
        {
            "source_id": "KS-Y",
            "source_type": "trade_rule",
            "publisher": "P",
            "jurisdictions": ["GB", "DE"],
            "scope": "organization",
        }
    )
    metadata = applicability(
        {"version_label": "v2", "effective_from": "2024-01-01", "effective_to": None}, source
    )
    assert metadata["jurisdictions"] == ["GB", "DE"]
    assert metadata["effective_from"] == "2024-01-01"
    assert metadata["missing"] == []


def test_invalid_chunks_are_rejected_before_anything_is_written():
    with pytest.raises(KnowledgeError):
        parse_chunks([])
    with pytest.raises(KnowledgeError):
        parse_chunks([{"chunk_id": "a", "text": "x"}, {"chunk_id": "a", "text": "y"}])
    with pytest.raises(KnowledgeError):
        parse_chunks([{"chunk_id": "a", "text": "  "}])
    with pytest.raises(KnowledgeError):
        parse_source({"source_id": "KS-X", "source_type": "web", "publisher": "P"})


def test_seed_fixtures_are_synthetic_with_version_and_effective_period(tmp_path):
    store = SQLiteStore(tmp_path / "k.db")
    result = KnowledgeService(store).seed()
    assert result == {"imported": 8, "published": 8}

    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))]
    assert len(payloads) == 8
    for payload in payloads:
        source = payload["source"]
        assert source["synthetic"] is True
        assert source["version_label"] in ("demo-1", "demo-2")
        assert source["effective_from"]
        assert "合成" in payload["title"] or "synthetic" in payload["title"].lower()
        assert source["license_reference"].startswith("synthetic")
    for version in store.list_knowledge_versions_all():
        assert version["status"] == "published"
        assert version["reviewed_by"] == "user_demo_reviewer"
        assert version["submitted_by"] == "user_demo_author"


def test_demo_corpus_has_72_published_chunks(tmp_path):
    store = SQLiteStore(tmp_path / "k.db")
    KnowledgeService(store).seed()

    rows = store.published_chunks()
    assert len(rows) == 72
    assert {row["source_id"] for row in rows} == {
        "KS-PRODUCT-001",
        "KS-RULES-001",
        "KS-POLICY-001",
        "KS-HELP-001",
        "KS-PRODUCT-001-EN",
        "KS-RULES-001-EN",
        "KS-POLICY-001-EN",
        "KS-HELP-002",
    }
    assert {row["version_id"] for row in rows} == {
        "KV-PRODUCT-001-v2",
        "KV-RULES-001-v2",
        "KV-POLICY-001-v2",
        "KV-HELP-001-v1",
        "KV-PRODUCT-001-EN-v1",
        "KV-RULES-001-EN-v1",
        "KV-POLICY-001-EN-v1",
        "KV-HELP-002-v1",
    }
    assert all(row["synthetic"] for row in rows)
    assert all(row["text"] for row in rows)
    assert {row["language"] for row in rows} == {"zh-CN", "en"}


# --- 2.3 CLI ----------------------------------------------------------------------------------


def test_cli_seed_import_review_and_list(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "seed"]) == 0
    seeded = json.loads(capsys.readouterr().out)
    assert seeded == {"imported": 8, "published": 8}

    fixture = FIXTURES / "product_faq.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["version_id"] = "KV-PRODUCT-001-v3"
    payload["version_label"] = "demo-3"
    payload["source"]["version_label"] = "demo-3"
    path = tmp_path / "product_v3.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert main(["--db", db, "import", str(path), "--submitter", "user_author"]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["status"] == "pending_review"

    # Self-review is refused by the CLI (exit code 1) and publishes nothing.
    assert main([
        "--db", db, "review", "KV-PRODUCT-001-v3", "--decision", "publish",
        "--reviewer", "user_author",
    ]) == 1
    assert "submitter cannot review" in capsys.readouterr().out

    assert main([
        "--db", db, "review", "KV-PRODUCT-001-v3", "--decision", "publish",
        "--reviewer", "user_reviewer",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "published"

    assert main(["--db", db, "list", "--source", "KS-PRODUCT-001"]) == 0
    versions = json.loads(capsys.readouterr().out)
    assert {row["status"] for row in versions} == {"published", "superseded"}


def test_cli_withdraw_with_unknown_version_exits_nonzero(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "withdraw", "--source", "KS-NONE", "--reason", "x"]) == 1
    assert "no withdrawable knowledge version" in capsys.readouterr().out