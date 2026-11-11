"""Immutable export versions.

Spec: `orchestration` → *导出标准文件*. The version number is generated here, never accepted from
the caller. One file per version is written with `O_EXCL`, so two racing exports can never claim
the same number.

The store is deliberately tiny: the POC has no database for exports, and a directory of
`v<n>.json` files keeps "immutable" easy to verify by hand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(doc_id: str) -> str:
    cleaned = _SAFE.sub("-", doc_id or "document").strip("-")
    return cleaned or "document"


class DocVersionStore:
    """Append-only version directory, one JSON file per version."""

    def __init__(self, root: str | Path | None = None) -> None:
        env = os.environ.get("SMART_EDIT_EXPORT_DIR")
        self.root = Path(root or env or "data/exports")
        self._lock = threading.Lock()

    def _dir(self, doc_id: str) -> Path:
        return self.root / _safe_name(doc_id)

    def next_version(self, doc_id: str) -> int:
        directory = self._dir(doc_id)
        if not directory.is_dir():
            return 1
        numbers = []
        for path in directory.glob("v*.json"):
            _, _, tail = path.stem.partition("v")
            if tail.isdigit():
                numbers.append(int(tail))
        return max(numbers, default=0) + 1

    def append(self, doc_id: str, payload: dict) -> dict:
        """Write one immutable version and return `{version_no, path, sha256}`."""
        with self._lock:
            directory = self._dir(doc_id)
            directory.mkdir(parents=True, exist_ok=True)
            return self._write_locked(directory, payload)

    def append_unique(
        self,
        doc_id: str,
        payload: dict,
        *,
        snapshot_id: str,
        policy_revision: str | None = None,
    ) -> dict:
        """Append unless this snapshot+policy was already exported; replay returns the first version.

        Exports are keyed by the audited snapshot and the gate policy that allowed it, not by the
        request: submitting the same candidate twice must not create a second immutable version,
        while a policy change legitimately produces a new one.
        """
        with self._lock:
            directory = self._dir(doc_id)
            directory.mkdir(parents=True, exist_ok=True)
            existing = self._find_snapshot_locked(directory, snapshot_id, policy_revision)
            if existing is not None:
                return existing
            return self._write_locked(directory, payload)

    def _find_snapshot_locked(
        self, directory: Path, snapshot_id: str, policy_revision: str | None
    ) -> dict | None:
        for path in sorted(directory.glob("v*.json")):
            _, _, tail = path.stem.partition("v")
            if not tail.isdigit():
                continue
            encoded = path.read_text(encoding="utf-8")
            try:
                record = json.loads(encoded)
            except json.JSONDecodeError:  # a corrupt file is not an idempotency hit
                continue
            if record.get("snapshot_id") != snapshot_id:
                continue
            recorded_revision = (record.get("gate") or {}).get("policy_revision")
            if recorded_revision != policy_revision:
                continue
            return {
                "version_no": int(tail),
                "path": str(path),
                "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            }
        return None

    def _write_locked(self, directory: Path, payload: dict) -> dict:
        version = self.next_version(directory.name)
        record = {**payload, "version_no": version}
        encoded = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
        target = directory / f"v{version}.json"
        with open(target, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {
            "version_no": version,
            "path": str(target),
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }

    def write_version(self, doc_id: str, payload: dict) -> dict:
        """Contract name for `append`; the version is generated, never accepted."""
        return self.append(doc_id, payload)

    def latest(self, doc_id: str) -> dict | None:
        directory = self._dir(doc_id)
        version = self.next_version(doc_id) - 1
        if version < 1:
            return None
        path = directory / f"v{version}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["DocVersionStore"]
