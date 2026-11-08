"""Graph nodes: they do exactly four things — call pure functions, write the trail,
write a `StageReport`, and clear `_candidates`.

**No business decision inside a node** (design §4): every judgement lives in the pure
functions under `app/parsing/*`, which keeps the "same input, same output" surface as large as
possible — the precondition for being able to explain a conclusion on site.
"""

from __future__ import annotations


def clear_candidates() -> list:
    """Clear `_candidates` by returning an empty list.

    `_candidates` is a **non-reducer** channel in `app/state.py`, so returning `[]` already means
    "overwrite with empty" — whether the update is applied by langgraph or by
    `app/runtime.merge_update`. langgraph's `Overwrite` wrapper is only required for channels that
    *have* a reducer; wrapping here would instead leak an `Overwrite` object into every plain-dict
    consumer (the chain executor, the API envelope, the tests).

    If `_candidates` ever gains a reducer, wrap the return value in `Overwrite([])` at that point.
    """
    return []