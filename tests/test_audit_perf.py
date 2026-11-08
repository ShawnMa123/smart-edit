"""Performance guard (design D12 #1): locating spans must not re-normalise the document per field.

The assertion on call counts is deterministic; the timing bound only catches catastrophic regressions.
"""

from __future__ import annotations

import time

from app.audit import evidence
from app.audit.planner import evidence_units
from app.parsing import normalize as normalize_module
from app.rules.types import PASS

DOCUMENT = ("保函条款 GUARANTEE CLAUSE " * 2200)[:50_000]
FIELD_COUNT = 15
# Measured ~20 ms for this document after the fix (314 ms before it); 0.5 s is a catastrophe guard.
TIME_BUDGET_SECONDS = 0.5


def _unit():
    return next(unit for unit in evidence_units() if unit.check_id == "EVIDENCE:provenance")


def _state() -> dict:
    fields = {}
    for index in range(FIELD_COUNT):
        span = DOCUMENT[index * 100 : index * 100 + 40]
        fields[f"f{index}"] = {
            "key": f"f{index}",
            "value": span,
            "status": "extracted",
            "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": span, "form_label": None},
            "notes": [],
        }
    return {
        "docs": [{"file_id": "F-1", "full_text": DOCUMENT}],
        "fields": fields,
        "extra_fields": {},
        "findings": [],
        "trail": [],
    }


def test_provenance_normalises_the_document_once(monkeypatch):
    """One normalisation of the document plus one per span — not one per field."""
    sizes: list[int] = []
    original = normalize_module.normalize_ws

    def counting(text: str) -> str:
        sizes.append(len(text))
        return original(text)

    monkeypatch.setattr(normalize_module, "normalize_ws", counting)

    result = evidence.evaluate_evidence_unit(_unit(), _state())

    assert result.status == PASS
    assert len([size for size in sizes if size > 1_000]) == 1, "the document must be normalised once"
    assert len(sizes) == FIELD_COUNT + 1, "plus one needle per field"


def test_provenance_stays_within_the_time_budget():
    best = min(_time_once() for _ in range(3))
    assert best < TIME_BUDGET_SECONDS, f"provenance check took {best:.3f}s"


def _time_once() -> float:
    started = time.perf_counter()
    evidence.evaluate_evidence_unit(_unit(), _state())
    return time.perf_counter() - started