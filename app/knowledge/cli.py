"""Knowledge CLI (task 2.3): seed, import, review, withdraw, list — all against the local store.

Usage:
    python -m app.knowledge.cli seed
    python -m app.knowledge.cli import fixtures/knowledge/product_faq.json --submitter user_a
    python -m app.knowledge.cli review KV-PRODUCT-001-v1 --decision publish --reviewer user_b
    python -m app.knowledge.cli withdraw KS-PRODUCT-001 --reason "superseded by policy"
    python -m app.knowledge.cli list --source KS-PRODUCT-001
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.assistant.store import SQLiteStore
from app.knowledge.models import KnowledgeError
from app.knowledge.service import KnowledgeService


def _store(args: argparse.Namespace) -> SQLiteStore:
    return SQLiteStore(args.db)


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.knowledge.cli")
    parser.add_argument(
        "--db", default=os.environ.get("SMART_EDIT_ASSISTANT_DB", "runs/assistant.db")
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="import + publish the synthetic fixtures")

    import_cmd = sub.add_parser("import", help="import one JSON fixture as pending_review")
    import_cmd.add_argument("path", type=Path)
    import_cmd.add_argument("--submitter", default="user_demo_author")

    review = sub.add_parser("review", help="publish or reject a pending version")
    review.add_argument("version_id")
    review.add_argument("--decision", choices=("publish", "reject"), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", default="reviewed via cli")

    withdraw = sub.add_parser("withdraw", help="withdraw one version or a whole source")
    withdraw.add_argument("--source", required=True)
    withdraw.add_argument("--version", default=None)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--actor", default="user_demo_reviewer")

    listing = sub.add_parser("list", help="list knowledge versions")
    listing.add_argument("--source", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = _store(args)
    service = KnowledgeService(store)
    try:
        if args.command == "seed":
            _print(service.seed())
        elif args.command == "import":
            payload = json.loads(args.path.read_text(encoding="utf-8"))
            payload.setdefault("version_label", payload.get("source", {}).get("version_label"))
            _print(service.import_document(payload, submitted_by=args.submitter))
        elif args.command == "review":
            _print(service.review(args.version_id, args.decision, args.reviewer, args.reason))
        elif args.command == "withdraw":
            _print(service.withdraw(args.source, args.version, args.reason, args.actor))
        else:
            _print(service.list_versions(args.source))
    except (KnowledgeError, KeyError, ValueError, PermissionError) as exc:
        print(f"knowledge error: {exc}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = ["build_parser", "main"]