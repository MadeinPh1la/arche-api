# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quote DTOs (Application Layer)

Purpose:
    Transport-agnostic data transfer objects used by use-cases/presenters.

Layer: application/schemas/dto
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from .base import BaseDTO


class QuoteDTO(BaseDTO):
    """DTO for a single quote."""

    ticker: str = Field(description="Upper-case ticker symbol", examples=["AAPL"])
    price: Decimal = Field(description="Last traded price as decimal", examples=["173.42"])
    currency: str = Field(description="ISO 4217 currency code", examples=["USD"])
    as_of: datetime = Field(
        description="UTC timestamp of the quote", examples=["2025-10-28T13:45:00Z"]
    )
    volume: int | None = Field(
        default=None, description="Latest volume if available", examples=[1250000]
    )


class QuotesBatchDTO(BaseDTO):
    """DTO for a batch of quotes."""

    items: list[QuoteDTO] = Field(description="Quotes for requested tickers")
