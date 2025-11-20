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

    Values:
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
        return self.value


@dataclass(frozen=True)
class HistoricalBar(BaseEntity):
    """A single OHLCV bar for a ticker at a given timestamp.

    Attributes:
        ticker: Uppercase ticker symbol.
        timestamp: UTC timestamp at bar close.
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Traded volume for the interval (may be None).
        interval: Interval used to aggregate this bar.
    """

    ticker: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    interval: BarInterval
