# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Market Data Domain Exceptions

Purpose:
    Exceptions representing domain/application error conditions related to
    external market data providers. Mapped to HTTP by adapters.

Layer: domain/exceptions
"""
from __future__ import annotations

from .base import DomainError


class MarketDataUnavailable(DomainError):
    """Third-party market data dependency is unavailable or timed out."""

    code = "MARKET_DATA_UNAVAILABLE"


class SymbolNotFound(DomainError):
    """Upstream has no data for the requested symbol(s)."""

    code = "SYMBOL_NOT_FOUND"


class MarketDataValidationError(DomainError):
    """Upstream returned an unexpected/invalid payload."""

    code = "UPSTREAM_SCHEMA_ERROR"
