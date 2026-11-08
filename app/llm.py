"""Model provider adapter.

Design: `openspec/changes/frontend-console/design.md` D6.

`SMART_EDIT_LLM` decides what `extract` runs with:

| value            | result                                                        |
|------------------|---------------------------------------------------------------|
| unset            | `None` — the stage fails loudly, no candidates are invented   |
| `fixture:<path>` | a callable replaying that JSON file, labelled via `.provider`  |
| `openai:<model>` | `NotImplementedError` — reserved, never a silent fallback      |

The returned callable is what `extract_node(..., llm=...)` already expects, so nothing else in the
pipeline needs to know where candidates come from — except the stage `reason`, which must say so
when a fixture is in play.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

FIXTURE_PREFIX = "fixture:"
OPENAI_PREFIX = "openai:"
ENV_VAR = "SMART_EDIT_LLM"


def resolve_llm(env_value: str | None = None):
    """Return an `llm` callable, or `None` when no provider is configured."""
    raw = (env_value if env_value is not None else os.environ.get(ENV_VAR, "")).strip()
    if not raw:
        return None

    if raw.startswith(FIXTURE_PREFIX):
        return _fixture_llm(Path(raw[len(FIXTURE_PREFIX) :]))

    if raw.startswith(OPENAI_PREFIX):
        raise NotImplementedError(
            f"{OPENAI_PREFIX}<model> is reserved but not implemented; no provider SDK is installed. "
            f"Use {FIXTURE_PREFIX}<path> for a fixture-backed run, or unset {ENV_VAR}."
        )

    raise ValueError(
        f"unrecognised {ENV_VAR} value {raw!r}; expected unset, {FIXTURE_PREFIX}<path>, "
        f"or {OPENAI_PREFIX}<model>"
    )


def _fixture_llm(path: Path):
    """Build a callable that always replays the fixture's candidates."""
    if not path.is_file():
        raise FileNotFoundError(f"{ENV_VAR}={FIXTURE_PREFIX}{path} — fixture file not found")

    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        raise ValueError(f"fixture {path} must contain a list of candidates")

    def _replay(prompt: str):  # noqa: ARG001 - signature matches the real provider
        return candidates

    # The label travels with the callable so `extract_node` can say where candidates came from.
    _replay.provider = f"{FIXTURE_PREFIX}{path}"  # type: ignore[attr-defined]
    return _replay