# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quote Entity

Purpose:
    Immutable domain representation of a latest market quote (no I/O).

Layer: domain/entities
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .base import BaseEntity


@dataclass(frozen=True, slots=True)
class Quote(BaseEntity):
    """Latest quote entity.

    Args:
        ticker: Canonical, upper-case ticker symbol.
        price: Last traded price (non-negative).
        currency: ISO 4217 code (e.g., 'USD').
        as_of: UTC timestamp for observation (timezone-aware).
        volume: Optional last-known traded volume (non-negative).

    Raises:
        ValueError: If invariants are violated (e.g., negative price).
    """

    ticker: str
    price: Decimal
    currency: str
    as_of: datetime
    volume: int | None = None

    def __post_init__(self) -> None:
        if not self.ticker or self.ticker != self.ticker.upper():
            raise ValueError("ticker must be upper-case non-empty")
        if self.price < 0:
            raise ValueError("price must be >= 0")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume must be >= 0 when provided")
        if self.as_of.tzinfo is None:
            object.__setattr__(self, "as_of", self.as_of.replace(tzinfo=UTC))
