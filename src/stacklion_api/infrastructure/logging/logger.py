"""
JSON Logger (Infrastructure Layer)

Purpose:
    Provide a structured JSON logger with lightweight request-context enrichment
    and safe fallbacks for all environments (dev/test/prod).

Design:
    - Single `get_json_logger(name)` accessor.
    - `configure_root_logging()` to initialize the root logger once.
    - Adds `request_id` if middleware set it in context vars or env.
    - Avoids crashes: never raises from enrichment path.

Layer:
    infrastructure/logging
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_REQUEST_ID_ENV_KEY = "REQUEST_ID"  # If you mirror this via middleware/contextvar


class _JsonFormatter(logging.Formatter):
    """Serialize log records into a stable JSON structure."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%f%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Optional enrichment (never fail)
        try:
            rid: str | None = getattr(record, "request_id", None) or os.getenv(_REQUEST_ID_ENV_KEY)
            if rid:
                payload["request_id"] = rid
        except Exception as exc:  # pragma: no cover - defensive
            payload["enrichment_error"] = str(exc)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Include any `extra=` keys if present (defensive: won't fail if absent)
        extras = getattr(record, "extra", None)
        if isinstance(extras, dict):
            payload.update(extras)

        return json.dumps(payload, ensure_ascii=False)


def configure_root_logging(level: str | int | None = None) -> None:
    """Initialize the root logger with a JSON stream handler (idempotent).

    Args:
        level: Optional logging level; if None, uses LOG_LEVEL env (default INFO).
    """
    root = logging.getLogger()
    if root.handlers:  # already configured (avoid duplicate logs)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)

    # Coerce to a valid level for mypy and logging
    env_level = os.getenv("LOG_LEVEL")
    resolved: int | str = (
        level if level is not None else (env_level.upper() if env_level else "INFO")
    )
    root.setLevel(resolved)


def get_json_logger(name: str) -> logging.Logger:
    """Return a JSON logger configured with a stream handler.

    If the root logger hasn't been configured yet, this function does *not*
    implicitly configure it; call `configure_root_logging()` at app startup.

    Args:
        name: Logger name (usually `__name__` of the caller).

    Returns:
        logging.Logger: Configured logger instance.
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
