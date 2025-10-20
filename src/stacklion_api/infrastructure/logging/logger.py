"""
JSON Logger (Infrastructure Layer)

Purpose:
    Provide a structured JSON logger with lightweight request-context enrichment
    and safe fallbacks for all environments (dev/test/prod).

Design:
    - Single `get_json_logger(name)` accessor.
    - Adds `request_id` if middleware set it in context vars.
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
            # Log enrichment failures without interrupting application flow.
            payload["enrichment_error"] = str(exc)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # Include extra=... dict if present
        for k, v in getattr(record, "extra", {}).items() if hasattr(record, "extra") else []:
            payload[k] = v

        return json.dumps(payload, ensure_ascii=False)


def get_json_logger(name: str) -> logging.Logger:
    """Return a JSON logger configured with a stream handler.

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
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    logger.propagate = False
    return logger
