"""Deterministic rule kernel for the standards audit group.

Nothing in this package may import a model provider or an HTTP client — `tests/test_rule_engine.py`
enforces that, because AT-01 (identical results for identical inputs) is the group's core promise.
"""