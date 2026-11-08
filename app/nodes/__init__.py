"""Graph nodes: they do exactly four things — call pure functions, write the trail,
write a `StageReport`, and clear `_candidates`.

**No business decision inside a node** (design §4): every judgement lives in the pure
functions under `app/parsing/*`, which keeps the "same input, same output" surface as large as
possible — the precondition for being able to explain a conclusion on site.
"""

from __future__ import annotations

try:  # langgraph is only needed when wiring the graph; pure-function tests must not depend on it
    from langgraph.types import Overwrite  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - plain override when langgraph is not installed
    Overwrite = None  # type: ignore[assignment]


def clear_candidates() -> object:
    """Clear `_candidates`.

    `_candidates` is a temporary channel: `normalize` must clear it, otherwise the checkpointer
    keeps it forever. When wiring the graph, use langgraph's `Overwrite([])`; without langgraph
    it degrades to a plain empty list — the only difference is multi-writer semantics within one
    step, which the unit-test path does not exercise.
    """
    return Overwrite([]) if Overwrite is not None else []