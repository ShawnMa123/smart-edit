"""Shared test fixtures.

Rule: **assertions over golden files** (agent-contract spec: "only the assertions are stable").
Builders live in `tests/helpers.py`; this file only holds fixtures.
"""

from __future__ import annotations

import pytest

from app.config import DEFAULT_FIELDS_PATH, load_fields_config


@pytest.fixture(scope="session")
def fields_yaml() -> dict[str, dict]:
    """The real `app/configs/fields.yaml`, so tests and production share one config."""
    return load_fields_config()


@pytest.fixture(scope="session")
def fields_config_path():
    return DEFAULT_FIELDS_PATH