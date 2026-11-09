"""LangGraph Studio entry point.

`langgraph.json` points at `graph` below. The graph is compiled with the same SQLite checkpointer
as the service, so a pause created in Studio can be resumed by the API with the same `thread_id`
(and vice versa).

Start it with:

    langgraph dev

The CLI is optional; `uvicorn app.api.main:app` does not import this module.
"""

from __future__ import annotations

from app.graph_factory import compile_graph

graph = compile_graph()

__all__ = ["graph"]
