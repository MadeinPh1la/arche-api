# Copyright (c)
# SPDX-License-Identifier: MIT
"""OpenTelemetry span helper (lightweight, safe).

Provides a small async context manager ``traced(name, **attrs)`` to wrap
individual operations with an OTEL span. If OTEL is not installed or is
disabled, the helper acts as a no-op.

This module is separate from the bootstrapper to keep concerns clean:
- `infrastructure.logging.tracing` initializes instrumentation and exporters.
- `infrastructure.observability.tracing` provides the convenience span helper.

Layer:
    infrastructure/observability
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


@asynccontextmanager
async def traced(_span_name: str, **_attrs: Any) -> AsyncIterator[None]:
    """Async context manager placeholder for tracing spans.

    Args:
        _span_name: Logical span name (ignored).
        **_attrs: Span attributes (ignored).

    Returns:
        AsyncIterator[None]: Yields control without side effects.
    """
    yield
