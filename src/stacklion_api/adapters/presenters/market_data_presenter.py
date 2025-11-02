# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter: Historical Quotes → HTTP Envelopes.

Synopsis:
    Maps application DTOs to stable HTTP schemas and attaches presentation
    headers (ETag, etc.). Uses canonical envelopes and avoids leaking domain
    concerns. No business logic or I/O belongs here.

Layer:
    adapters/presenters

Design:
    * Accepts application DTOs (HistoricalBarDTO) and returns HTTP-layer models.
    * Attaches `ETag` when provided by the use-case to support conditional GETs.
    * Emits timestamps in RFC 3339/ISO 8601 with trailing 'Z' (UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Response

from stacklion_api.adapters.presenters.base_presenter import BasePresenter
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope
from stacklion_api.adapters.schemas.http.quotes import HistoricalBarHTTP
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO


def _iso8601_z(dt: datetime) -> str:
    """Render an aware/naive datetime as RFC 3339/ISO string with 'Z' suffix.

    Args:
        dt: Datetime (aware or naive).

    Returns:
        str: ISO 8601 string normalized to UTC with trailing 'Z'.
    """
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.isoformat().replace("+00:00", "Z")


class MarketDataPresenter(BasePresenter[HistoricalBarHTTP]):
    """Presenter for market-data list responses (historical OHLCV)."""

    def present_list(
        self,
        *,
        response: Response,
        items: list[HistoricalBarDTO],
        total: int,
        page: int,
        page_size: int,
        etag: str | None = None,
    ) -> PaginatedEnvelope[HistoricalBarHTTP]:
        """Render a paginated list of historical bars as a canonical envelope.

        Args:
            response: Mutable response to attach HTTP headers (e.g., ETag).
            items: Current page of historical bars.
            total: Total number of bars available for the query.
            page: 1-based page index.
            page_size: Items per page.
            etag: Weak/strong ETag to attach (if provided).

        Returns:
            PaginatedEnvelope[HistoricalBarHTTP]: Canonical HTTP schema instance.

        Notes:
            * The router/controller handle 304 logic. When a body is returned,
              we attach the `ETag` header here for clients and caches.
        """
        if etag:
            response.headers["ETag"] = etag

        http_items = [
            HistoricalBarHTTP(
                ticker=i.ticker,
                timestamp=_iso8601_z(i.timestamp),
                open=str(i.open),
                high=str(i.high),
                low=str(i.low),
                close=str(i.close),
                volume=(str(i.volume) if i.volume is not None else None),
                interval=i.interval.value,
            )
            for i in items
        ]

        return PaginatedEnvelope[HistoricalBarHTTP](
            page=page,
            page_size=page_size,
            total=total,
            items=http_items,
        )
