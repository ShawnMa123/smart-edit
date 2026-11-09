"""Operation trail (`TrailEntry` write-back).

Contract: `openspec/changes/poc-skeleton/design.md` §8. Shared-layer pure functions never
touch `state`; they return the entries they want recorded as a **list of dicts**, and the
node writes them back in one go via `record_many()`, which assigns the ids.

Id scheme (contract §4.6): `"agent1.extract#003"` — counters are **per agent**,
grouped by `(agent, stage)`, so parallel agent2 / agent3 runs never fight over numbers.
"""

from __future__ import annotations

from app.state import AGENT_IDS, OVERREACH_OPS, TRAIL_OPS


def _next_seq(state: dict, agent: str, stage: str) -> int:
    """Number of existing entries for this (agent, stage) pair, plus one."""
    seq = 0
    for entry in state.get("trail", []) or []:
        if entry.get("agent") == agent and entry.get("stage") == stage:
            seq += 1
    return seq + 1


def _make_id(agent: str, stage: str, seq: int) -> str:
    return f"{agent}.{stage}#{seq:03d}"


def _validate(agent: str, op: str) -> None:
    if agent not in AGENT_IDS:
        raise ValueError(f"unknown agent: {agent!r}, allowed: {AGENT_IDS}")
    if op not in TRAIL_OPS:
        raise ValueError(f"unknown trail op: {op!r}, allowed: {TRAIL_OPS}")
    # Overreach ops (summarize/rewrite/drop) **may** be recorded — recording them is the point.
    # Detection is `overreach_entries()` / Agent 4's job, not ours.


def record(
    state: dict,
    *,
    agent: str,
    stage: str,
    op: str,
    before: str | None = None,
    after: str | None = None,
    ref: str | None = None,
    model: str | None = None,
    prompt_hash: str | None = None,
    detail: dict | None = None,
) -> dict:
    """Return `{"trail": [entry]}` for the reducer to append. Ids increment per agent."""
    _validate(agent, op)
    entry = {
        "id": _make_id(agent, stage, _next_seq(state, agent, stage)),
        "agent": agent,
        "stage": stage,
        "op": op,
        "before": before,
        "after": after,
        "ref": ref,
        "model": model,
        "prompt_hash": prompt_hash,
        "detail": detail or {},
    }
    return {"trail": [entry]}


def record_many(state: dict, *, agent: str, stage: str, entries: list[dict]) -> dict:
    """For shared-layer receipts (`ExtractResult.trail_entries` / `NormalizeResult.trail_entries`).

    Receipt entries carry business fields only (`op` / `before` / `after` / `ref` /
    `model` / `prompt_hash` / `detail`); `id` / `agent` / `stage` are filled in here —
    pure functions hold no `state` and therefore cannot allocate a sequence number
    (contract §6, rule 1).
    """
    out: list[dict] = []
    seq = _next_seq(state, agent, stage)
    for raw in entries:
        op = raw.get("op")
        _validate(agent, op)
        out.append(
            {
                "id": _make_id(agent, stage, seq),
                "agent": agent,
                "stage": raw.get("stage") or stage,
                "op": op,
                "before": raw.get("before"),
                "after": raw.get("after"),
                "ref": raw.get("ref"),
                "model": raw.get("model"),
                "prompt_hash": raw.get("prompt_hash"),
                "detail": raw.get("detail") or {},
            }
        )
        seq += 1
    return {"trail": out}


def overreach_entries(state: dict) -> list[dict]:
    """Overreach entries (`summarize` / `rewrite` / `drop`). Acceptance requires this to be empty."""
    return [e for e in state.get("trail", []) or [] if e.get("op") in OVERREACH_OPS]