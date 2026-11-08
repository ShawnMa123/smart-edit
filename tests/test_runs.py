"""Run store (tasks 3.1-3.2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.llm import resolve_llm
from app.runs import RunStore, UnknownRun
from app.runtime import execute_chain

FIXTURE = Path("fixtures/llm/extract_sample.json")
SAMPLE = Path("fixtures/llm/sample_document.txt")


def _store(tmp_path) -> RunStore:
    return RunStore(runs_dir=tmp_path / "runs")


def test_create_get_dispose(tmp_path):
    """3.1 Lifecycle of a run."""
    store = _store(tmp_path)
    thread_id, state = store.create()

    assert store.get(thread_id) is state
    assert store.workdir(thread_id).is_dir()
    assert len(store) == 1

    store.dispose(thread_id)
    assert len(store) == 0
    with pytest.raises(UnknownRun):
        store.get(thread_id)


def test_unknown_run_raises(tmp_path):
    """3.1 An unknown id raises the error the API maps to 404 unknown_run."""
    with pytest.raises(UnknownRun) as excinfo:
        _store(tmp_path).get("R-doesnotexist")
    assert excinfo.value.thread_id == "R-doesnotexist"


def test_store_upload_stays_inside_the_run_dir(tmp_path):
    store = _store(tmp_path)
    thread_id, _ = store.create()

    path, digest = store.store_upload(thread_id, "../escape.txt", b"hello")

    assert path.parent == store.workdir(thread_id), "upload must not escape the run directory"
    assert path.name == "escape.txt"
    assert len(digest) == 64


def test_concurrent_triggers_serialise(tmp_path):
    """3.2 Two concurrent chains do not interleave reducer appends."""
    store = _store(tmp_path)
    thread_id, state = store.create()
    path, digest = store.store_upload(thread_id, SAMPLE.name, SAMPLE.read_bytes())
    state["files"] = [
        {
            "file_id": f"F-{digest[:8]}",
            "filename": path.name,
            "mime": "text/plain",
            "path": str(path),
            "sha256": digest,
        }
    ]
    llm = resolve_llm(f"fixture:{FIXTURE}")
    chain = ["parse", "extract", "normalize"]

    async def one_trigger() -> None:
        async with store.lock(thread_id):
            execute_chain(state, chain, llm=llm)

    async def both() -> None:
        await asyncio.gather(one_trigger(), one_trigger())

    asyncio.run(both())

    parsed = [report for report in state["stages"] if report["stage"] == "parse"]
    assert len(parsed) == 1, "the second trigger must see the first one's done stage, not re-run it"
    assert [report["stage"] for report in state["stages"]] == ["parse", "extract", "normalize"]
    assert state["trail"], "trail survived both triggers"
    assert state["fields"]["guarantee_amount"]["status"] == "extracted"