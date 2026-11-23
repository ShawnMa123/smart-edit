"""Run the synthetic knowledge-assistant evaluation (task 6.4/6.4a).

Usage:
    .venv/bin/python scripts/assistant_eval.py              # fresh temporary DB (default)
    .venv/bin/python scripts/assistant_eval.py --db runs/assistant.db
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from app.assistant.bootstrap import build_services
from app.assistant.eval import run_eval
from app.assistant.service import AssistantService


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic knowledge-assistant evaluation")
    parser.add_argument(
        "--db",
        default=None,
        help="database path; default is a fresh temporary DB so the report is reproducible",
    )
    args = parser.parse_args()

    db_path = args.db
    if db_path is None:
        # The local runs/assistant.db is intentionally ignored and may hold an older seed; a fresh
        # temporary DB keeps the 25-question report reproducible from any checkout.
        db_path = str(Path(tempfile.mkdtemp(prefix="assistant-eval-")) / "assistant.db")
    services = build_services(db_path=db_path, mode="test")
    report = run_eval(AssistantService(services))
    summary = {key: value for key, value in report.items() if key != "cases"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for case in report["cases"]:
        mark = "ok" if case["outcome_ok"] and case["citation_hit"] else "MISS"
        print(
            f"{case['id']} {mark:4} outcome={case['outcome']:<22} "
            f"expected={case['expected_outcome']:<22} citations={case['citation_chunk_ids']}"
        )

    # Statute decision layer (offline, no network, no model) — printed beside the synthetic baseline
    # so the two numbers are never confused: the baseline measures the local corpus, this one measures
    # how often a statute-backed answer is possible at all.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from statute_eval import run as run_statute_eval
    except Exception:  # pragma: no cover - the statute fixture may be absent in a trimmed checkout
        return 0
    statute = run_statute_eval()
    print("\nstatute comparison (offline decision layer):")
    print(
        json.dumps(
            {
                "synthetic_corpus_baseline": {
                    "cases": summary["total"],
                    "outcome_accuracy": summary["outcome_accuracy"],
                    "citation_hit_rate": summary["citation_hit_rate"],
                    "statute_citation_rate": 0.0,
                    "note": "语料全部为合成来源，结构上不可能出现法规引用",
                },
                "statute_fixture": {
                    "cases": statute["cases"],
                    "reason_accuracy": statute["reason_accuracy"],
                    "statute_citation_rate": statute["statute_citation_rate"],
                    "unusable_reasons": statute["unusable_reasons"],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())