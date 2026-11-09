"""Runtime seams between the HTTP layer and the stage nodes.

Until `poc-skeleton` §8 lands there is no graph, so nothing applies the reducers that
`app/state.py` declares. This module owns the two things that must exist exactly once:

1. `merge_update()` — the **single** production implementation of "merge a node update into state"
   (`findings` / `trail` / `stages` append; everything else overwrites). `tests/helpers.apply_update`
   re-exports it so tests and production can never drift.
2. `execute_chain()` — runs a stage chain from `plan_standalone()` through the existing nodes,
   skipping stages that already finished.

Design: `openspec/changes/frontend-console/design.md` D1-D2.
"""

from __future__ import annotations

from app.config import FieldsConfigError, load_fields_config
from app.nodes.audit import audit_node
from app.nodes.extract import extract_node
from app.nodes.normalize import normalize_node
from app.nodes.parse import parse_node
from app.regulatory.node import regulatory_node
from app.stages import STAGE_TARGETS, latest_stage
from app.standalone import clear_previous_outputs

# The only keys with a reducer in `app/state.py`. Anything else overwrites.
REDUCER_KEYS = ("findings", "trail", "stages")

NODES = {
    "parse": parse_node,
    "extract": extract_node,
    "normalize": normalize_node,
    "agent3": regulatory_node,
    "audit": audit_node,
}


class UnknownStage(ValueError):
    """A chain named a stage that is not registered as a stage target."""


def merge_update(state: dict, update: dict) -> dict:
    """Apply one node's partial update to `state`, honouring the reducer keys."""
    for key, value in update.items():
        if key in REDUCER_KEYS:
            state[key] = (state.get(key) or []) + list(value)
        else:
            state[key] = value
    return state


def is_done(state: dict, stage: str) -> bool:
    """True when the latest report for `stage` is `done`."""
    report = latest_stage(state.get("stages") or [], stage)
    return bool(report) and report.get("status") == "done"


def execute_chain(
    state: dict,
    chain: list[str],
    *,
    llm=None,
    fields_yaml: dict[str, dict] | None = None,
    template_reference: dict | None = None,
    retriever=None,
    answerer=None,
) -> dict:
    """Run `chain` in order, merging each node update into `state` (mutated in place).

    - An unregistered stage name raises **before** any node runs.
    - A stage whose latest report is `done` is skipped: `extract` consumes `_candidates` and
      `normalize` clears them, so re-running them would rebuild `fields` from nothing and turn every
      required field into a `missing` placeholder (design Risks).
    - `template_reference` reaches the audit node only; it asks for template-driven audit (design D18).
    """
    unknown = [stage for stage in chain if stage not in STAGE_TARGETS]
    if unknown:
        raise UnknownStage(f"unregistered stage target(s): {unknown}")

    if fields_yaml is None:
        try:
            fields_yaml = load_fields_config()
        except FieldsConfigError:
            # Let `normalize_node` report the configuration failure as three `failed` stages.
            fields_yaml = None

    field_keys = list(fields_yaml) if fields_yaml else []

    for stage in chain:
        # Agent 3 is explicitly re-runnable: a second trigger must replace its old legal opinion,
        # retrieval and `R-` findings instead of showing a stale one. Other done stages stay reusable.
        if is_done(state, stage) and stage != "agent3":
            continue
        # Only the target's own conclusions are cleared; `stages` / `trail` stay append-only.
        stale = clear_previous_outputs(state, stage)
        if stale:
            # `findings` is a reducer key in the graph, but the chain executor is a plain dict:
            # replacing means assignment here, never `merge_update` (which would append).
            if "findings" in stale:
                state["findings"] = stale.pop("findings")
            merge_update(state, stale)
        if stage == "parse":
            update = parse_node(state)
        elif stage == "extract":
            update = extract_node(state, llm=llm, field_keys=field_keys)
        elif stage == "agent3":
            update = regulatory_node(state, retriever=retriever, answerer=answerer)
        elif stage == "audit":
            update = audit_node(state, template_reference=template_reference)
        else:
            update = normalize_node(state, fields_yaml=fields_yaml)
        merge_update(state, update)
    return state