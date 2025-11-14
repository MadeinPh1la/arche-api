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
    log.info("ingest.done", extra={"symbol": "MSFT", "rows": 123})
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Final

_REQUEST_ID_ENV_KEY: Final[str] = "REQUEST_ID"


class _JsonFormatter(logging.Formatter):
    """Serialize log records into a stable JSON structure."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:
        """Return a JSON-serialized string for the given record.

        Args:
            record: A ``logging.LogRecord`` instance.

        Returns:
            str: JSON payload.
        """
        # Timestamp (UTC-like rendering without tz offset to remain pipeline-friendly)

        ts_base = self.formatTime(record, self.default_time_format)
        ts = self.default_msec_format % (ts_base, record.msecs)

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Optional request_id enrichment—never throw
        try:
            rid: str | None = getattr(record, "request_id", None) or os.getenv(_REQUEST_ID_ENV_KEY)
            if rid:
                payload["request_id"] = rid
        except Exception as exc:  # pragma: no cover (defensive)
            payload["enrichment_error"] = str(exc)

        # Exceptions (if any)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Accept additional context via record.extra (standard `extra=` dict)
        extras = getattr(record, "extra", None)
        if isinstance(extras, dict):
            payload.update(extras)

        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_root_logging(level: str | int | None = None) -> None:
    """Initialize the root logger with a JSON stream handler (idempotent).

    Args:
        level: Logging level or level name. If ``None``, use env ``LOG_LEVEL`` or ``INFO``.
    """
    root = logging.getLogger()
    if root.handlers:
        # Already configured—prevent duplicate handlers on hot reload
        return

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)

    env_level = os.getenv("LOG_LEVEL")
    resolved: int | str = (
        level if level is not None else (env_level.upper() if env_level else "INFO")
    )
    root.setLevel(resolved)


def get_json_logger(name: str) -> logging.Logger:
    """Return a JSON logger with a stream handler (non-propagating).

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

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)

    env_level = os.getenv("LOG_LEVEL")
    logger.setLevel(env_level.upper() if env_level else "INFO")
    logger.propagate = False
    return logger
