# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Use-case: Get Historical Quotes (read-through cache + ETag).

Synopsis:
    Orchestrates cache lookup, vendor gateway fetch, normalization, and ETag
    calculation. Strictly application-level logic—no HTTP/infra details.

Layer:
    application/use_cases

Design:
    * Read-through cache with short TTL to reduce upstream load.
    * Weak ETag computed from page content and total count to enable 304s.
    * Input validation: ensures `from_ <= to` at the application boundary.
    * No HTTP concerns; presenters/controllers handle envelopes/headers.

"""

from __future__ import annotations

import hashlib
import json
from time import monotonic

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol
from stacklion_api.infrastructure.observability.metrics_market_data import (
    market_data_cache_hits_total,
    market_data_cache_misses_total,
    stacklion_usecase_historical_quotes_latency_seconds,
)


class GetHistoricalQuotesUseCase:
    """Fetch historical OHLCV bars with read-through caching and ETag support.

    This use-case encapsulates the core orchestration for historical data:
    cache lookup, upstream fetch via the market data gateway, and ETag
    composition for conditional HTTP responses (handled by presenters).

    Args:
        cache: Cache port used for JSON serialization of paged results.
        gateway: Market data gateway adhering to the protocol contract.

    Notes:
        * This class is framework-agnostic. It must not import FastAPI or
          infrastructure concerns. It operates purely on DTOs.
    """

    def __init__(self, *, cache: CachePort, gateway: MarketDataGatewayProtocol) -> None:
        """Initialize the use-case.

        Args:
            cache: Cache port implementation.
            gateway: Market data gateway implementation (protocol).
        """
        self._cache = cache
        self._gateway = gateway

    @staticmethod
    def _cache_key(q: HistoricalQueryDTO) -> str:
        """Create a stable cache key for the query.

        The key is normalized: symbols uppercased + sorted, ISO8601 instants,
        and the explicit interval/page/page_size. The result is a hex-encoded
        SHA-256 digest suitable for Redis keys.

        Args:
            q: Query parameters.

        Returns:
            str: Hex-encoded SHA-256 digest for the normalized key.
        """
        key = {
            "tickers": sorted(t.upper() for t in q.tickers),
            "from": q.from_.isoformat(),
            "to": q.to.isoformat(),
            "interval": q.interval.value,
            "page": q.page,
            "page_size": q.page_size,
        }
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _etag(items: list[HistoricalBarDTO], total: int) -> str:
        """Compute a weak ETag for a page of items.

        The ETag combines the total count with a stable projection of each
        item's identity and closing price. We intentionally avoid including all
        OHLC fields to keep the tag compact, while still changing whenever the
        page composition or closes change.

        Args:
            items: Bars on the current page.
            total: Total number of items for the query.

        Returns:
            str: Weak ETag header value (e.g., W/"<sha256>").
        """
        digest = hashlib.sha256()
        digest.update(str(total).encode("utf-8"))
        for it in items:
            # Ticker|ISO8601 timestamp|close is sufficient to capture page identity.
            digest.update(f"{it.ticker}|{it.timestamp.isoformat()}|{it.close}".encode())
        return f'W/"{digest.hexdigest()}"'

    async def execute(self, q: HistoricalQueryDTO) -> tuple[list[HistoricalBarDTO], int, str]:
        """Execute the use-case.

        Validates input window, attempts a cache read; on miss, fetches from the
        market data gateway, stores a compact JSON payload with TTL, and returns
        the items along with total count and an ETag.

        Args:
            q: Query parameters (tickers, from_, to, interval, page, page_size).

        Returns:
            Tuple[List[HistoricalBarDTO], int, str]: Items, total count, and ETag.

        Raises:
            MarketDataValidationError: If `from_` is after `to`.
        """
        if q.from_ > q.to:
            raise MarketDataValidationError("'from' must be <= 'to'")

        start = monotonic()
        outcome = "success"
        surface = "historical_quotes"
        try:
            key = f"hist:{self._cache_key(q)}"

            # 1) Cache read
            cached = await self._cache.get_json(key)
            if cached:
                items = [HistoricalBarDTO(**it) for it in cached["items"]]
                etag = str(cached["etag"])
                total = int(cached["total"])
                market_data_cache_hits_total.labels(surface).inc()
                return items, total, etag

            # Cache miss
            market_data_cache_misses_total.labels(surface).inc()

            # 2) Upstream fetch on miss
            items, total = await self._gateway.get_historical_bars(q)

            # 3) ETag & cache write
            etag = self._etag(items, total)
            await self._cache.set_json(
                key,
                {"items": [it.model_dump() for it in items], "total": total, "etag": etag},
                ttl=900,
            )
            return items, total, etag

        except Exception:
            outcome = "error"
            raise
        finally:
            stacklion_usecase_historical_quotes_latency_seconds.labels(
                q.interval.value, outcome
            ).observe(monotonic() - start)
