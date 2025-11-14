# Copyright (c)
# SPDX-License-Identifier: MIT
"""Minimal async circuit breaker (in-memory).

State machine:
    - CLOSED -> count failures; when threshold reached, go OPEN.
    - OPEN   -> fail-fast until recovery timeout expires; then HALF-OPEN.
    - HALF-OPEN -> allow limited calls; on success -> CLOSED; on failure -> OPEN.

This is process-local. For distributed breakers, use a shared store.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    """Simple circuit breaker suitable for HTTP client protection."""

    failure_threshold: int
    recovery_timeout_s: float
    half_open_max_calls: int

    _state: str = "CLOSED"  # CLOSED|OPEN|HALF_OPEN
    _failures: int = 0
    _opened_at: float = 0.0
    _half_open_calls: int = 0
    _lock: asyncio.Lock = asyncio.Lock()

    @asynccontextmanager
    async def guard(self, _key: str) -> AsyncIterator[None]:  # noqa: C901
        """Guard an async call with the breaker."""
        async with self._lock:
            now = time.monotonic()
            if self._state == "OPEN":
                if now - self._opened_at >= self.recovery_timeout_s:
                    self._state = "HALF_OPEN"
                    self._half_open_calls = 0
                else:
                    raise RuntimeError("circuit_open")
            if self._state == "HALF_OPEN":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise RuntimeError("circuit_half_open_limit")
                self._half_open_calls += 1

        try:
            yield
        except Exception:
            async with self._lock:
                if self._state == "HALF_OPEN":
                    self._state = "OPEN"
                    self._opened_at = time.monotonic()
                else:
                    self._failures += 1
                    if self._failures >= self.failure_threshold:
                        self._state = "OPEN"
                        self._opened_at = time.monotonic()
            raise
        else:
            async with self._lock:
                if self._state == "HALF_OPEN":
                    self._state = "CLOSED"
                    self._failures = 0
                elif self._state == "CLOSED":
                    self._failures = 0
