"""LangGraph Studio entry point compiles the same graph (task 10.3)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_langgraph_config_points_at_the_studio_graph():
    config = json.loads(Path("langgraph.json").read_text(encoding="utf-8"))
    assert config["graphs"]["smart-edit"] == "./app/studio.py:graph"


def test_studio_graph_exposes_the_frozen_nodes(monkeypatch, tmp_path):
    monkeypatch.setenv("SMART_EDIT_CHECKPOINT_DB", str(tmp_path / "checkpoints.sqlite"))
    import app.studio

    importlib.reload(app.studio)
    nodes = set(app.studio.graph.nodes)
    assert {
        "ingest",
        "parse",
        "extract",
        "normalize",
        "reset",
        "agent2",
        "agent3",
        "merge",
        "agent4",
        "repair",
        "hitl",
        "gate",
        "export",
    } <= nodes
