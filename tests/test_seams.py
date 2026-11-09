"""All four seam fixtures are executable and green (contract task 10.4).

Run any fixture directly as well:
    .venv/Scripts/python.exe -m pytest fixtures/seam_a_to_b/assert.py -q
"""

from __future__ import annotations

import inspect
import runpy
from pathlib import Path

import pytest

FIXTURES = ("seam_a_to_b", "seam_a_to_c", "seam_ac_to_d", "seam_bd_to_gate")


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_pair_exists(name):
    root = Path("fixtures") / name
    assert (root / "input.json").is_file()
    assert (root / "assert.py").is_file()


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_assertions_pass(name):
    module = runpy.run_path(str(Path("fixtures") / name / "assert.py"))
    checks = sorted(key for key in module if key.startswith("test_") and callable(module[key]))
    assert checks, f"{name} has no executable assertions"
    for check in checks:
        function = module[check]
        params = inspect.signature(function).parameters
        if not params:
            function()
        elif set(params) == {"key"}:
            # A `@pytest.mark.parametrize("key", ...)` fixture: use its exact declared values.
            values = None
            for mark in getattr(function, "pytestmark", []):
                if mark.name == "parametrize" and mark.args and mark.args[0] == "key":
                    values = list(mark.args[1])
                    break
            if values is None:
                values = list((module.get("FIELDS") or module.get("ALL_VALUES") or {}))
            assert values, f"{name}.{check} has no keys to exercise"
            for key in values:
                function(key)
        else:
            pytest.skip(f"{name}.{check} needs unsupported parameters {sorted(params)}")
