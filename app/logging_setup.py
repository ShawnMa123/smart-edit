"""Application logging for local development.

The app never used stdlib logging before: everything a run did was written to SQLite/audit rows,
while `scripts/dev.sh` sent uvicorn output to a temp file. This module gives the app one stdout
channel so `./scripts/dev.sh` can stream useful, non-secret lifecycle lines to the terminal (and
mirror them to a log file).

Usage:
    from app.logging_setup import get_logger

    logger = get_logger("assistant")
    logger.info("run=%s outcome=%s", run_id, outcome)

Set `SMART_EDIT_LOG_LEVEL` (default `INFO`, e.g. `DEBUG`) to change verbosity. Never log
questions, document text, API keys or provider credentials.
"""

from __future__ import annotations

import logging
import os
import sys

APP_LOGGER = "smart_edit"
LOG_LEVEL_ENV = "SMART_EDIT_LOG_LEVEL"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-26s %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def _level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    return getattr(logging, (value or "INFO").upper(), logging.INFO)


def configure_logging(level: str | int | None = None) -> logging.Logger:
    """Attach one stdout handler to the `smart_edit` logger (idempotent)."""
    logger = logging.getLogger(APP_LOGGER)
    resolved = level if level is not None else os.environ.get(LOG_LEVEL_ENV)
    if getattr(logger, "_smart_edit_configured", False):
        if resolved is not None:
            logger.setLevel(_level(resolved))
        return logger

    logger.setLevel(_level(resolved))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
    handler._smart_edit_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    # Uvicorn configures the root logger; keep our lines single and predictable.
    logger.propagate = False
    logger._smart_edit_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    configure_logging()
    return logging.getLogger(APP_LOGGER if not name else f"{APP_LOGGER}.{name}")


__all__ = ["APP_LOGGER", "LOG_LEVEL_ENV", "configure_logging", "get_logger"]