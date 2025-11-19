# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""HTTP Schemas package (Adapters Layer).

Purpose:
    Public, adapter-facing HTTP schema surface for Stacklion.

    This module re-exports the canonical envelopes and resource schemas used by
    routers and presenters. It intentionally does NOT expose BaseHTTPSchema to
    keep the base class internal to this package.

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.adapters.schemas.http.quotes import (
    HistoricalBarHTTP,
    HistoricalQuotesRequest,
    QuoteItem,
    QuotesBatch,
)

__all__ = [
    # Envelopes
    "ErrorObject",
    "ErrorEnvelope",
    "SuccessEnvelope",
    "PaginatedEnvelope",
    # Quotes / historical schemas
    "QuoteItem",
    "QuotesBatch",
    "HistoricalQuotesRequest",
    "HistoricalBarHTTP",
]
