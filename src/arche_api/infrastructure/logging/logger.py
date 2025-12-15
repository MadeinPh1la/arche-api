# src/arche_api/infrastructure/logging/logger.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Structured JSON logging utilities.

This module exposes an idempotent root configurator and a per-module logger
factory that produce JSON logs suitable for ingestion by log pipelines.

Features:
    * Google-style docstrings and strict typing.
    * Stable keys: ``ts``, ``level``, ``logger``, ``message``.
    * Automatic enrichment with ``request_id`` and ``trace_id`` via contextvars.
    * Fallback enrichment via record attributes or environment variables.
    * No-throw enrichment path (defensive).

Typical usage:
    configure_root_logging()
    log = get_json_logger(__name__)
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "configure_root_logging",
    "get_json_logger",
    "set_request_context",
    "get_request_id",
    "get_trace_id",
]

_REQUEST_ID_ENV_KEY = "REQUEST_ID"

# Per-request correlation context (task-local via contextvars).
_REQUEST_ID_CTX: ContextVar[str | None] = ContextVar("arche_request_id", default=None)
_TRACE_ID_CTX: ContextVar[str | None] = ContextVar("arche_trace_id", default=None)

# OpenTelemetry is an optional dependency; imported lazily and defensively.
_otel_trace: Any | None = None
try:  # pragma: no cover - OTEL may not be installed
    from opentelemetry import trace as _otel_trace_mod

    _otel_trace = _otel_trace_mod
except Exception:  # pragma: no cover - OTEL may not be installed
    _otel_trace = None


def set_request_context(*, request_id: str | None = None, trace_id: str | None = None) -> None:
    """Set per-request correlation identifiers on the current context.

    Args:
        request_id: Correlation identifier from ``X-Request-ID``, if any.
        trace_id: Distributed tracing identifier (hex string), if any.

    Notes:
        This function is additive: passing only one of the arguments will update
        that value and leave the other unchanged. It is safe to call from
        multiple middleware layers in the same request.
    """
    if request_id is not None:
        _REQUEST_ID_CTX.set(request_id)
    if trace_id is not None:
        _TRACE_ID_CTX.set(trace_id)


def get_request_id() -> str | None:
    """Return the current request id from contextvars, if any."""
    return _REQUEST_ID_CTX.get(None)


def get_trace_id() -> str | None:
    """Return the current trace id from contextvars, if any."""
    return _TRACE_ID_CTX.get(None)


def _derive_otel_trace_id() -> str | None:
    """Derive a hex trace id from the current OpenTelemetry span, if any.

    Returns:
        Hex-encoded trace id suitable for log correlation, or ``None`` if
        OpenTelemetry is not installed or no active span exists.
    """
    if _otel_trace is None:
        return None
    try:
        span = _otel_trace.get_current_span()
        ctx = span.get_span_context()
        trace_id = getattr(ctx, "trace_id", 0)
        # OTEL uses 0 as the "invalid" trace id sentinel.
        if not trace_id:
            return None
        return f"{int(trace_id):032x}"
    except Exception:  # pragma: no cover - defensive only
        return None


class _JsonFormatter(logging.Formatter):
    """JSON log formatter emitting stable keys and optional extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON object.

        Args:
            record: Logging record.

        Returns:
            JSON-encoded log line.
        """
        ts = datetime.now(tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Request id enrichment — prefer record attribute, then contextvar, then env.
        try:
            rid: str | None = (
                getattr(record, "request_id", None)
                or _REQUEST_ID_CTX.get(None)
                or os.getenv(_REQUEST_ID_ENV_KEY)
            )
            if rid:
                payload["request_id"] = rid
        except Exception as exc:  # pragma: no cover (defensive)
            payload["request_id_error"] = str(exc)

        # Trace id enrichment — prefer record attribute, then contextvar, then OTEL span.
        try:
            tid: str | None = getattr(record, "trace_id", None) or _TRACE_ID_CTX.get(None)
            if not tid:
                tid = _derive_otel_trace_id()
            if tid:
                payload["trace_id"] = tid
        except Exception as exc:  # pragma: no cover (defensive)
            payload["trace_id_error"] = str(exc)

        # Exceptions: guard against None in exc_info tuple.
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type is not None:
                payload["exc_type"] = exc_type.__name__
            if exc_value is not None:
                payload["exc_message"] = str(exc_value)

        # Extra dict, if any (e.g., access_log fields).
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
        Configured logger.
    """
    logger = logging.getLogger(name)
    # Delegate formatting and level to the root logger.
    logger.propagate = True
    return logger
