"""Build / inspect the vendored regulatory index.

Usage:

    python -m app.regulatory.index status
    python -m app.regulatory.index build
    python -m app.regulatory.index build --keyword-only     # no embedding gateway needed
    python -m app.regulatory.index build --limit 2          # smoke build
    python -m app.regulatory.index manifest

Paths in `data/regulatory/config.json` are relative to the repository root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "data" / "regulatory" / "config.json"


def _config_path(value: str | None) -> Path:
    raw = value or os.environ.get("SMART_EDIT_RAG_CONFIG") or str(DEFAULT_CONFIG)
    return Path(raw)


def _load_manifest(cfg, value: str | None):
    from mercatoria.manifest import load_manifest, write_manifest

    path = Path(value) if value else cfg.resolved_manifest_path()
    if path.is_file():
        return load_manifest(path)
    return write_manifest(cfg.resolved_corpus_dir(), path)


def build(
    *,
    config_path: str | None = None,
    limit: int = 0,
    out: str | None = None,
    activate: bool = True,
    keyword_only: bool = False,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    from mercatoria.config import load_config
    from mercatoria.store import build_index

    cfg = load_config(_config_path(config_path))
    manifest = _load_manifest(cfg, None)
    if limit > 0:
        manifest = {**manifest, "docs": manifest["docs"][:limit]}
    result = build_index(
        manifest,
        cfg,
        out or cfg.resolved_index_dir(),
        activate=activate,
        keyword_only=keyword_only,
        progress=progress,
    )
    return result


def status(*, config_path: str | None = None) -> dict[str, Any]:
    from mercatoria.config import load_config
    from mercatoria.store import IndexNotFound, open_current

    cfg = load_config(_config_path(config_path))
    try:
        index = open_current(cfg.resolved_index_dir())
    except IndexNotFound as exc:
        return {"status": "not_built", "error": str(exc), "config": str(_config_path(config_path))}
    try:
        return index.corpus_block()
    finally:
        index.close()


def _progress(stage: str, done: int, total: int) -> None:
    if stage in {"chunk", "embed", "done"}:
        print(f"{stage}: {done}/{total}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.regulatory.index")
    parser.add_argument("--config", default=None, help="JSON config path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="rebuild the SQLite index")
    p_build.add_argument("--limit", type=int, default=0, help="only first N documents (smoke)")
    p_build.add_argument("--out", default=None, help="index directory or .db path")
    p_build.add_argument("--no-activate", action="store_true")
    p_build.add_argument(
        "--keyword-only", action="store_true", help="BM25 only; no embedding gateway required"
    )

    p_status = sub.add_parser("status", help="print the active index metadata")
    p_manifest = sub.add_parser("manifest", help="regenerate the corpus manifest")
    p_manifest.add_argument("--out", default=None)

    args = parser.parse_args(argv)
    if args.command == "build":
        result = build(
            config_path=args.config,
            limit=args.limit,
            out=args.out,
            activate=not args.no_activate,
            keyword_only=args.keyword_only,
            progress=_progress,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(status(config_path=args.config), ensure_ascii=False, indent=2))
        return 0

    from mercatoria.config import load_config
    from mercatoria.manifest import write_manifest

    cfg = load_config(_config_path(args.config))
    path = Path(args.out) if args.out else cfg.resolved_manifest_path()
    manifest = write_manifest(cfg.resolved_corpus_dir(), path)
    print(json.dumps({"documents": len(manifest["docs"]), "path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
