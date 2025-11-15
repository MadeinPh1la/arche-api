# src/stacklion_api/infrastructure/logging/logger.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Structured JSON logging utilities.

This module exposes an idempotent root configurator and a per-module logger
factory that produce JSON logs suitable for ingestion by log pipelines.

Features:
    * Google-style docstrings and strict typing.
    * Stable keys: ``ts``, ``level``, ``logger``, ``message``.
    * Optional enrichment with ``request_id`` via record attribute or env var.
    * No-throw enrichment path (defensive).

Typical usage:
    configure_root_logging()
    log = get_json_logger(__name__)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

__all__ = ["configure_root_logging", "get_json_logger"]

_REQUEST_ID_ENV_KEY = "REQUEST_ID"


class _JsonFormatter(logging.Formatter):
    """JSON log formatter emitting stable keys and optional extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON object.

        Args:
            record: Logging record.

        Returns:
            str: JSON-encoded log line.
        """
        ts = datetime.now(tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Optional request_id enrichment—never throw.
        try:
            rid: str | None = getattr(record, "request_id", None) or os.getenv(_REQUEST_ID_ENV_KEY)
            if rid:
                payload["request_id"] = rid
        except Exception as exc:  # pragma: no cover (defensive)
            payload["enrichment_error"] = str(exc)

        # Exceptions: guard against None in exc_info tuple.
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type is not None:
                payload["exc_type"] = exc_type.__name__
            if exc_value is not None:
                payload["exc_message"] = str(exc_value)

        # Extra dict, if any.
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_root_logging(level: str | int | None = None) -> None:
    """Initialize the root logger with a JSON stream handler (idempotent).

    Args:
        level: Logging level or level name. If ``None``, use env ``LOG_LEVEL`` or ``INFO``.
    """
    root = logging.getLogger()

    env_level = os.getenv("LOG_LEVEL")
    resolved: int | str = (
        level if level is not None else (env_level.upper() if env_level else "INFO")
    )
    root.setLevel(resolved)

    if root.handlers:
        # Already configured—prevent duplicate handlers on hot reload.
        return

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def get_json_logger(name: str) -> logging.Logger:
    """Return a module-specific logger backed by the JSON root handler.

    This does *not* implicitly configure the root logger. Call
    :func:`configure_root_logging` once at startup for global defaults.

    Args:
        name: Logger name, typically ``__name__`` of the caller.

    Returns:
        logging.Logger: Configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    # Delegate formatting and level to the root logger.
    logger.propagate = True
    return logger
