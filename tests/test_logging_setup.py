"""Logging setup (dev terminal visibility): one idempotent stdout handler."""

from __future__ import annotations

import logging

from app.logging_setup import APP_LOGGER, configure_logging, get_logger


def test_configure_logging_is_idempotent_and_respects_the_level():
    first = configure_logging("DEBUG")
    second = configure_logging("INFO")

    assert first is second
    assert first is logging.getLogger(APP_LOGGER)
    assert first.level == logging.INFO
    ours = [handler for handler in first.handlers if getattr(handler, "_smart_edit_handler", False)]
    assert len(ours) == 1
    assert first.propagate is False


def test_get_logger_returns_a_namespaced_child():
    assert get_logger().name == APP_LOGGER
    assert get_logger("assistant").name == f"{APP_LOGGER}.assistant"