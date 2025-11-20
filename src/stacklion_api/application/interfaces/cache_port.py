# src/stacklion_api/application/interfaces/cache_port.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Application Interface: Cache Port.

Synopsis:
    Minimal JSON cache behavior used by use cases. Enables swapping Redis,
    in-memory, or other cache implementations.

Layer:
    application/interfaces
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class CachePort(Protocol):
    """JSON cache with TTL semantics.

    Implementations must store values as JSON-serializable mappings and apply
    TTL in seconds. Implementations are free to ignore very small TTLs (<= 0)
    and treat them as "do not cache" semantics.
    """

    async def get_json(self, key: str) -> Mapping[str, Any] | None:
        """Get a JSON-serializable value by key.

        Args:
            key: Cache key (already namespaced if applicable).

        Returns:
            Deserialized JSON mapping if present, else ``None``.
        """

    async def set_json(self, key: str, value: Mapping[str, Any], *, ttl: int) -> None:
        """Set a JSON-serializable value with TTL.

        Args:
            key: Cache key (already namespaced if applicable).
            value: JSON-serializable mapping.
            ttl: Time-to-live in seconds.
        """
