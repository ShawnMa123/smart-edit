"""Seed and reconcile the synthetic knowledge corpus (A only).

The corpus is explicitly synthetic. `seed_knowledge()` imports every fixture as `processing`, moves it
to `pending_review` only after all chunks are stored, then publishes it with a **different** reviewer
id. It is also idempotent and version-aware: an older local database gains missing sources and newer
fixture versions on the next local/test startup instead of remaining silently stale.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge"
SUBMITTER = "user_demo_author"
REVIEWER = "user_demo_reviewer"


def _ensure_source(store, source: dict) -> None:
    if store.get_knowledge_source(source["source_id"]):
        return
    store.create_knowledge_source(
        source_id=source["source_id"],
        source_type=source["source_type"],
        publisher=source["publisher"],
        language=source.get("language", "zh-CN"),
        scope=source.get("scope", "organization"),
        organization_id=source.get("organization_id"),
        license_reference=source.get("license_reference", "synthetic-demo"),
        synthetic=bool(source.get("synthetic", True)),
        jurisdictions=source.get("jurisdictions", []),
    )


def seed_knowledge(
    store,
    *,
    publish: bool = True,
    submitter: str = SUBMITTER,
    reviewer: str = REVIEWER,
) -> dict[str, int]:
    imported = 0
    published = 0
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = payload["source"]
        _ensure_source(store, source)
        version_id = payload.get("version_id") or f"KV-{source['source_id']}-{source['version_label']}"
        existing = store.get_knowledge_version(version_id)
        if existing:
            # A previous seed may have stopped at pending_review; finish the same fixture version
            # instead of creating a duplicate or skipping it forever.
            if publish and existing["status"] == "pending_review":
                store.review_knowledge_version(
                    version_id, "publish", reviewer, "synthetic demo review"
                )
                published += 1
            continue
        store.create_knowledge_version(
            version_id=version_id,
            source_id=source["source_id"],
            title=payload["title"],
            version_label=source["version_label"],
            effective_from=source.get("effective_from"),
            effective_to=source.get("effective_to"),
            submitted_by=submitter,
        )
        store.add_knowledge_chunks(version_id, source["source_id"], payload["chunks"])
        store.mark_pending_review(version_id)
        imported += 1
        if publish:
            store.review_knowledge_version(version_id, "publish", reviewer, "synthetic demo review")
            published += 1
    return {"imported": imported, "published": published}


if __name__ == "__main__":  # pragma: no cover - manual seed
    from app.assistant.store import SQLiteStore

    result = seed_knowledge(SQLiteStore())
    print(f"knowledge seeds: {result}")