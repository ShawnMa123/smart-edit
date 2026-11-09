"""The main graph: one path for the first run and every repair.

Contract: `openspec/changes/poc-skeleton/design.md` §10. Node names and edges are frozen; the
implementation behind each node is free to change.

Why these edges:

- `reset` runs even on the first pass. `Overwrite([])` is idempotent, so "first run" and "rerun
  after a user edit" take the same code path instead of drifting apart.
- `agent2` and `agent3` are ordinary parallel edges off `reset`. `Send` would require both branches
  to write the same reducer-less key; the only dynamic fan-out (multiple files) stays inside
  `parse`.
- `agent4` does not go straight to `gate`. A fixable failure gets one bounded repair; only then
  does the run reach the review panel.
- `gate -> END` on a blocked decision. Sending the user back to `hitl` creates the "change, fail,
  change, fail" loop the spec forbids.
"""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from app.config import FieldsConfigError, load_fields_config
from app.nodes.agent2 import agent2_node
from app.nodes.audit import audit_node
from app.nodes.export import export_node
from app.nodes.extract import extract_node
from app.nodes.hitl import hitl_node
from app.nodes.ingest import ingest_node
from app.nodes.merge import merge_node
from app.nodes.normalize import normalize_node
from app.nodes.parse import parse_node
from app.nodes.pipeline_gate import export_gate_node
from app.nodes.repair import repair_node, route_after_repair, route_after_verifier
from app.nodes.reset import reset_node
from app.regulatory.node import regulatory_node
from app.state import EditState


def route_after_hitl(state: dict) -> str:
    """`recheck` means the user changed a field and wants the pipeline to run again."""
    if state.get("recheck") and int(state.get("recheck_count") or 0) < 3:
        return "reset"
    return "gate"


def route_after_gate(state: dict) -> str:
    """Only a passed gate may export; a blocked one ends the run."""
    return "export" if (state.get("gate") or {}).get("verdict") == "pass" else "end"


def _fields_config() -> dict[str, dict] | None:
    try:
        return load_fields_config()
    except FieldsConfigError:
        # The `normalize` node turns this into three `failed` stage reports with a reason.
        return None


def build_graph(
    *,
    llm=None,
    field_keys: list[str] | None = None,
    retriever=None,
    answerer=None,
    agent2=None,
    audit_schema=None,
    audit_bundles=None,
    audit_templates=None,
    template_reference: dict | None = None,
    versions=None,
    operation: str | None = None,
) -> StateGraph:
    """Build the uncompiled graph; `graph_factory.compile_graph` adds the checkpointer."""
    fields_yaml = _fields_config()
    resolved_keys = field_keys if field_keys is not None else list(fields_yaml or {})

    graph = StateGraph(EditState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("parse", parse_node)
    graph.add_node(
        "extract",
        partial(extract_node, llm=llm, field_keys=resolved_keys),
    )
    graph.add_node(
        "normalize",
        partial(normalize_node, fields_yaml=fields_yaml),
    )
    graph.add_node("reset", reset_node)
    graph.add_node("agent2", agent2 or agent2_node)
    graph.add_node(
        "agent3",
        partial(regulatory_node, retriever=retriever, answerer=answerer),
    )
    graph.add_node("merge", merge_node)
    graph.add_node(
        "agent4",
        partial(
            audit_node,
            schema=audit_schema,
            bundles=audit_bundles,
            templates=audit_templates,
            template_reference=template_reference,
        ),
    )
    graph.add_node("repair", repair_node)
    graph.add_node("hitl", hitl_node)
    if operation is None:
        graph.add_node("gate", export_gate_node)
    else:
        graph.add_node("gate", partial(export_gate_node, operation=operation))
    graph.add_node("export", partial(export_node, versions=versions))

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "parse")
    graph.add_edge("parse", "extract")
    graph.add_edge("extract", "normalize")
    graph.add_edge("normalize", "reset")
    graph.add_edge("reset", "agent2")
    graph.add_edge("reset", "agent3")
    graph.add_edge(["agent2", "agent3"], "merge")
    graph.add_edge("merge", "agent4")
    graph.add_conditional_edges(
        "agent4", route_after_verifier, {"repair": "repair", "hitl": "hitl"}
    )
    graph.add_conditional_edges(
        "repair",
        route_after_repair,
        {"agent2": "agent2", "agent3": "agent3", "hitl": "hitl"},
    )
    graph.add_conditional_edges(
        "hitl", route_after_hitl, {"reset": "reset", "gate": "gate"}
    )
    graph.add_conditional_edges(
        "gate", route_after_gate, {"export": "export", "end": END}
    )
    graph.add_edge("export", END)
    return graph


__all__ = ["build_graph", "route_after_gate", "route_after_hitl"]
