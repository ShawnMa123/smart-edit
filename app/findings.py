"""`Finding` numbering + `emit` trail entries (one implementation shared by all three agents).

Contract: `openspec/changes/poc-skeleton/design.md` §2 (frozen file);
decision details: `openspec/changes/agent-normalize/design.md` §7.5.

[Why numbering does not happen in the pure function] The next id depends on
`state["findings"]`, while `build_fields()` is pure. Numbering and trail writing live here so
Agent 2 / Agent 3 can reuse the same implementation and the three prefixes never collide.
"""

from __future__ import annotations

from app.state import FINDING_PREFIX, Finding


def materialize_findings(
    state: dict,
    drafts: list[dict],
    *,
    agent: str = "agent1",
    stage: str = "normalize",
) -> dict:
    """Number the drafts and write `emit` trail entries. Returns `{"findings": [...], "trail": [...]}`.

    Drafts carry business fields only (`source` / `kind` / `rule_id` / `severity` /
    `blocking` / `resolved` / `resolution` / `field_keys` / `message` / `evidence` /
    `citation` / `suggestion`) and **no `id`**: numbering must read existing `findings`
    so a rerun never reuses a number.

    `agent` / `stage` default to `agent1` / `normalize` (A's call site); B / C reuse the same
    implementation with their own values, and the prefix comes from `draft["source"]`
    via `FINDING_PREFIX`.
    """
    out_findings: list[Finding] = []
    out_trail: list[dict] = []
    counters: dict[str, int] = {}
    for existing in state.get("findings", []) or []:
        prefix, _, tail = str(existing.get("id", "")).partition("-")
        if tail.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(tail))

    for draft in drafts:
        prefix = FINDING_PREFIX[draft["source"]]
        counters[prefix] = counters.get(prefix, 0) + 1
        fid = f"{prefix}-{counters[prefix]:03d}"
        out_findings.append(Finding(id=fid, **draft))  # type: ignore[typeddict-item]
        out_trail.append(
            {
                "agent": agent,
                "stage": stage,
                "op": "emit",
                "before": None,
                "after": fid,
                "ref": ",".join(draft.get("field_keys") or []) or None,
                "model": None,
                "prompt_hash": None,
                "detail": {"rule_id": draft["rule_id"], "kind": draft["kind"]},
            }
        )
    return {"findings": out_findings, "trail": out_trail}