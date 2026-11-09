"""Control plane for a checkpointed run.

Spec: `poc-skeleton/tasks.md` 8.8. Three entry points, one lock:

- `start(thread_id)` — run from `START` to the first `interrupt` (or `END`)
- `resume(thread_id, payload)` — continue an interrupt; the same payload is applied once
- `events(thread_id)` — replay node / stage / trail views from the checkpointer

The API's in-memory `RunStore` remains the object the envelope reads; after every graph step the
runner copies the checkpoint values back into it, so clients never see a half-written state.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from langgraph.types import Command

from app.graph_factory import compile_graph
from app.runs import RunStore as ProcessRunStore
from app.store import RunStore as Ledger


def _resume_key(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _interrupt_values(interrupts) -> list:
    values = []
    for item in interrupts or ():
        values.append(getattr(item, "value", item))
    return values


class Runner:
    """One compiled graph + one durable ledger per application."""

    def __init__(
        self,
        runs: ProcessRunStore,
        *,
        llm=None,
        checkpointer_path: str | Path | None = None,
        ledger: Ledger | None = None,
        graph=None,
        graph_kwargs: dict | None = None,
    ) -> None:
        self.runs = runs
        self._ledger = ledger
        self._graph = graph
        self._checkpointer_path = checkpointer_path
        self._graph_kwargs = dict(graph_kwargs or {})
        self._graph_kwargs.setdefault("llm", llm)
        self._lock = threading.RLock()

    @property
    def ledger(self) -> Ledger:
        if self._ledger is None:
            with self._lock:
                if self._ledger is None:
                    self._ledger = Ledger()
        return self._ledger

    @property
    def graph(self):
        if self._graph is None:
            with self._lock:
                if self._graph is None:
                    self._graph = compile_graph(
                        checkpointer_path=self._checkpointer_path,
                        **self._graph_kwargs,
                    )
        return self._graph

    def _config(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _sync(self, thread_id: str, values: dict) -> None:
        state = self.runs.get(thread_id)
        state.clear()
        state.update(values)
        self.ledger.save_state(thread_id, values)

    def _result(self, thread_id: str, *, status: str, payloads: list) -> dict:
        return {
            "thread_id": thread_id,
            "status": status,
            "interrupt": payloads[0] if payloads else None,
            "interrupts": payloads,
        }

    def start(self, thread_id: str) -> dict:
        """Run (or observe) the graph; never re-executes a completed thread."""
        with self._lock:
            config = self._config(thread_id)
            state = self.graph.get_state(config)
            if state.interrupts:
                self._sync(thread_id, dict(state.values or {}))
                payloads = _interrupt_values(state.interrupts)
                return self._result(thread_id, status="interrupted", payloads=payloads)
            if state.values and not state.next:
                # Already finished; a new run is a new thread, not a silent replay.
                self._sync(thread_id, dict(state.values))
                return self._result(thread_id, status="complete", payloads=[])

            result = self.graph.invoke(dict(self.runs.get(thread_id)), config)
            latest = self.graph.get_state(config)
            values = dict(latest.values or {})
            self._sync(thread_id, values)
            payloads = _interrupt_values(
                latest.interrupts or (result.get("__interrupt__") if isinstance(result, dict) else ())
            )
            status = "interrupted" if payloads else "complete"
            self.ledger.record_event(
                thread_id, "run", {"status": status, "interrupt": payloads[0] if payloads else None}
            )
            return self._result(thread_id, status=status, payloads=payloads)

    def resume(self, thread_id: str, payload: object) -> dict:
        """Apply one resume payload exactly once, then run to the next interrupt or `END`."""
        with self._lock:
            config = self._config(thread_id)
            key = _resume_key(payload)
            if self.ledger.resume_seen(thread_id, key):
                # Duplicate submission: report the current checkpoint, do not invoke the graph.
                latest = self.graph.get_state(config)
                payloads = _interrupt_values(latest.interrupts)
                self._sync(thread_id, dict(latest.values or {}))
                status = "interrupted" if payloads else "complete"
                return self._result(thread_id, status=status, payloads=payloads)

            latest = self.graph.get_state(config)
            if not latest.interrupts:
                payloads: list = []
                status = "complete"
            else:
                result = self.graph.invoke(Command(resume=payload), config)
                latest = self.graph.get_state(config)
                payloads = _interrupt_values(
                    latest.interrupts
                    or (result.get("__interrupt__") if isinstance(result, dict) else ())
                )
                status = "interrupted" if payloads else "complete"
            # Written only after the graph applied it: a crash mid-resume can be retried, while a
            # successful duplicate is still ignored.
            self.ledger.mark_resume(thread_id, key)
            self._sync(thread_id, dict(latest.values or {}))
            self.ledger.record_event(
                thread_id,
                "resume",
                {"status": status, "key": key, "interrupt": payloads[0] if payloads else None},
            )
            return self._result(thread_id, status=status, payloads=payloads)

    def events(self, thread_id: str) -> list[dict]:
        """Oldest-first node / stage / trail timeline reconstructed from checkpoints."""
        config = self._config(thread_id)
        history = list(self.graph.get_state_history(config))
        if not history:
            return self.ledger.events(thread_id)

        events: list[dict] = []
        previous_stages = 0
        previous_trail = 0
        previous_next: tuple = ()
        for checkpoint in reversed(history):
            step = (checkpoint.metadata or {}).get("step")
            values = checkpoint.values or {}
            stages = values.get("stages") or []
            trail = values.get("trail") or []

            if previous_next:
                events.append(
                    {
                        "type": "node",
                        "step": step,
                        "node": previous_next[0],
                        "next": list(checkpoint.next or ()),
                    }
                )
            for report in stages[previous_stages:]:
                events.append({"type": "stage", "step": step, **report})
            for entry in trail[previous_trail:]:
                events.append({"type": "trail", "step": step, **entry})

            previous_stages = max(previous_stages, len(stages))
            previous_trail = max(previous_trail, len(trail))
            previous_next = tuple(checkpoint.next or ())
        return events

    def close(self) -> None:
        self.ledger.close()


__all__ = ["Runner"]
