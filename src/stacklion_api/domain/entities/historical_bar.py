# src/stacklion_api/domain/entities/historical_bar.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Historical Bars (Domain Entities).

Synopsis:
    Immutable domain primitives for historical OHLCV bars (EOD and intraday).
    Contains strict value semantics and interval enumeration.

Layer:
    domain/entities
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from stacklion_api.domain.entities.base import BaseEntity


class BarInterval(str, Enum):
    """Supported bar intervals.

    Attributes:
        I1M:  1-minute bars (canonical short name).
        I1MIN: 1-minute bars (compat alias, same value as I1M).
        I5M:  5-minute bars.
        I15M: 15-minute bars.
        I1H:  1-hour bars.
        I1D:  1-day (EOD) bars.
    """

    # 1-minute – keep existing short name and add a compat alias for tests.
    I1M = "1m"
    I1MIN = "1m"  # alias used by some tests / callers

    I5M = "5m"
    I15M = "15m"
    I1H = "1h"
    I1D = "1d"

    def __str__(self) -> str:  # pragma: no cover - trivial
        """Return the canonical string representation for this interval."""
        return self.value


@dataclass(frozen=True)
class HistoricalBar(BaseEntity):
    """A single OHLCV bar for a ticker at a given timestamp.

    Attributes:
        ticker:
            Uppercase ticker symbol (non-empty).
        timestamp:
            Datetime at bar close (UTC or timezone-aware as enforced upstream).
        open:
            Open price for the interval (must be >= 0).
        high:
            High price for the interval (must be >= 0).
        low:
            Low price for the interval (must be >= 0 and <= high).
        close:
            Close price for the interval (must be >= 0).
        volume:
            Traded volume for the interval (may be None, otherwise >= 0).
        interval:
            Interval used to aggregate this bar.
    """

    ticker: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    interval: BarInterval

    def __post_init__(self) -> None:
        """Enforce core invariants for historical bars."""
        super().__post_init__()

        if not isinstance(self.ticker, str) or not self.ticker.strip():
            raise ValueError("HistoricalBar.ticker must be a non-empty string.")
        if self.ticker != self.ticker.upper():
            raise ValueError("HistoricalBar.ticker must be upper-case.")

        for field_name in ("open", "high", "low", "close"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"HistoricalBar.{field_name} must be >= 0.")

        if self.low > self.high:
            raise ValueError("HistoricalBar.low must be <= HistoricalBar.high.")

        if self.volume is not None and self.volume < 0:
            raise ValueError("HistoricalBar.volume must be >= 0 when provided.")
