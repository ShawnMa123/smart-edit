"""Durable control-plane ledger (tasks 8.7-8.9)."""

from __future__ import annotations

from app.store import RunStore


def test_state_roundtrip_and_last_write_wins(tmp_path):
    store = RunStore(tmp_path / "ledger.sqlite")
    store.save_state("R-1", {"run_id": "R-1", "fields": {"a": {"value": "1"}}})
    assert store.load_state("R-1")["fields"]["a"]["value"] == "1"

    store.save_state("R-1", {"run_id": "R-1", "fields": {}})
    assert store.load_state("R-1")["fields"] == {}
    assert store.load_state("R-2") is None
    store.close()


def test_resume_key_is_claimed_once_but_mark_is_explicit(tmp_path):
    store = RunStore(tmp_path / "ledger.sqlite")
    assert store.claim_resume("R-1", "k1") is True
    assert store.claim_resume("R-1", "k1") is False
    assert store.resume_seen("R-1", "k1")

    assert not store.resume_seen("R-1", "k2")
    store.mark_resume("R-1", "k2")
    assert store.resume_seen("R-1", "k2")
    store.close()


def test_events_are_ordered_per_run(tmp_path):
    store = RunStore(tmp_path / "ledger.sqlite")
    assert store.record_event("R-1", "run", {"status": "interrupted"}) == 1
    assert store.record_event("R-1", "resume", {"status": "complete"}) == 2
    assert store.record_event("R-2", "run", {"status": "complete"}) == 1

    events = store.events("R-1")
    assert [event["seq"] for event in events] == [1, 2]
    assert [event["kind"] for event in events] == ["run", "resume"]
    assert events[0]["status"] == "interrupted"
    store.close()
