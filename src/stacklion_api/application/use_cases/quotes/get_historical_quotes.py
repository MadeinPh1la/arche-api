# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Use-case: Get Historical Quotes (A6).

Synopsis:
    Validates the time window, performs a read-through cache for paginated
    historical bars (EOD / intraday), and returns DTOs plus a stable weak ETag.

Metrics:
    * UC latency (Histogram): stacklion_usecase_historical_quotes_latency_seconds
    * Cache hits/misses (Counters):
        - stacklion_market_data_cache_hits_total
        - stacklion_market_data_cache_misses_total
    * Upstream observation (Histogram + Error Counter via helper):
        - stacklion_market_data_gateway_latency_seconds
        - stacklion_market_data_errors_total{reason="...",route="/v1/quotes/historical:..."}
    * Error counter helper (raised exceptions are still re-thrown):
        - inc_market_data_error("rate_limited", "/v1/quotes/historical")

Design:
    * Orchestrates cache -> gateway fetch -> cache write.
    * Prefers a provider ETag when available; otherwise computes a canonical,
      deterministic **weak** ETag (W/"...") for list payloads.
    * Tolerates legacy and modern gateway interfaces:
        - Tries a named-args call first
        - Falls back to positional args
        - Lastly, falls back to passing the DTO
      Accepts 3-tuple, 2-tuple, iterable, or dict returns and normalizes them.

Layer:
    application/use_cases
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.schemas.dto.quotes import (
    HistoricalBarDTO,
    HistoricalQueryDTO,
)
from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.observability.metrics_market_data import (
    get_market_data_cache_hits_total,
    get_market_data_cache_misses_total,
    get_usecase_historical_quotes_latency_seconds,
    inc_market_data_error,
    observe_upstream_request,
)

__all__ = ["GetHistoricalQuotesUseCase"]


# =============================================================================
# Helpers: canonical JSON + ETag
# =============================================================================


def _is_dataclass_instance(x: Any) -> bool:
    """Return True only for dataclass **instances** (not classes)."""
    return is_dataclass(x) and not isinstance(x, type)


def _json_default(value: Any) -> Any:
    """Deterministic serializer for hashing.

    Handles Decimal, datetime, Pydantic v2 models, and dataclass **instances**.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):  # Pydantic v2 first (avoids accidental asdict on DTOs)
        return value.model_dump()
    if _is_dataclass_instance(value):
        return asdict(value)
    raise TypeError(f"Unsupported type for JSON hashing: {type(value)!r}")


def _dto_to_dict(item: HistoricalBarDTO | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a bar DTO or mapping to a plain dict suitable for hashing/caching."""
    if hasattr(item, "model_dump"):  # Pydantic v2 first
        return cast(dict[str, Any], item.model_dump())
    if isinstance(item, Mapping):
        return dict(item)
    if _is_dataclass_instance(item):
        return cast(dict[str, Any], asdict(item))
    return dict(getattr(item, "__dict__", {}))


def _weak_quoted_etag(obj: Any) -> str:
    """Compute a weak, quoted SHA-256 ETag from canonical JSON."""
    material = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default).encode(
        "utf-8"
    )
    digest = hashlib.sha256(material).hexdigest()
    return f'W/"{digest}"'


# =============================================================================
# Use case
# =============================================================================
class GetHistoricalQuotesUseCase:
    """Fetch historical OHLCV bars with read-through caching and stable ETags."""

    def __init__(self, *, cache: CachePort, gateway: Any) -> None:
        """Initialize the use case."""
        self._cache = cache
        self._gateway = gateway

    async def execute(
        self, q: HistoricalQueryDTO, *, if_none_match: str | None = None
    ) -> tuple[list[HistoricalBarDTO], int, str]:
        """Execute the use case."""
        if q.from_ > q.to:
            raise MarketDataValidationError("'from' must be <= 'to'")

        key = self._cache_key(q)

        with get_usecase_historical_quotes_latency_seconds().time():
            cached = await self._try_cache_get(q, key)
            if cached is not None:
                return cached

            get_market_data_cache_misses_total().labels("historical_quotes").inc()

            endpoint = "eod" if str(q.interval).lower() in {"1d", "barinterval.i1d"} else "intraday"
            with observe_upstream_request(
                provider="marketstack", endpoint=endpoint, interval=str(q.interval)
            ):
                try:
                    items, total, provider_etag = await self._get_from_gateway(q)
                except (
                    MarketDataRateLimited,
                    MarketDataQuotaExceeded,
                    MarketDataBadRequest,
                    MarketDataUnavailable,
                ) as e:
                    reason = {
                        MarketDataRateLimited: "rate_limited",
                        MarketDataQuotaExceeded: "quota_exceeded",
                        MarketDataBadRequest: "bad_request",
                        MarketDataUnavailable: "unavailable",
                    }[type(e)]
                    inc_market_data_error(reason, "/v1/quotes/historical")
                    raise

            etag = provider_etag or _weak_quoted_etag(
                {
                    "page": q.page,
                    "page_size": q.page_size,
                    "total": total,
                    "items": [_dto_to_dict(i) for i in items],
                }
            )

            await self._cache_set_page(key, items, total, etag)
            return items, total, etag

    # -------------------------- Internals (small helpers) -------------------------- #
    def _cache_key(self, q: HistoricalQueryDTO) -> str:
        tickers_key = ",".join(sorted(map(str.upper, q.tickers)))
        return (
            f"hist:{tickers_key}:{str(q.interval)}:"
            f"{q.from_.isoformat()}:{q.to.isoformat()}:p{q.page}:s{q.page_size}"
        )

    async def _try_cache_get(
        self, q: HistoricalQueryDTO, key: str
    ) -> tuple[list[HistoricalBarDTO], int, str] | None:
        cached = await self._cache.get_json(key)
        if not cached:
            return None
        get_market_data_cache_hits_total().labels("historical_quotes").inc()
        cached_items = cached.get("items", [])
        cached_total = int(cached.get("total", 0))
        etag = cached.get("etag") or _weak_quoted_etag(
            {"page": q.page, "page_size": q.page_size, "total": cached_total, "items": cached_items}
        )
        items = [(i if hasattr(i, "model_dump") else HistoricalBarDTO(**i)) for i in cached_items]
        return items, cached_total, etag

    async def _cache_set_page(
        self, key: str, items: list[HistoricalBarDTO], total: int, etag: str
    ) -> None:
        cache_obj = {"items": [_dto_to_dict(i) for i in items], "total": total, "etag": etag}
        await _cache_set_json_compat(self._cache, key, cache_obj, ttl=300)

    async def _get_from_gateway(
        self, q: HistoricalQueryDTO
    ) -> tuple[list[HistoricalBarDTO], int, str | None]:
        """Invoke the gateway and normalize the return."""
        try:
            maybe = await self._gateway.get_historical_bars(
                tickers=q.tickers,
                date_from=q.from_,
                date_to=q.to,
                interval=q.interval,
                limit=q.page_size,
                offset=max(0, (q.page - 1) * q.page_size),
            )
            return _normalize_gateway_return(maybe)
        except TypeError:
            pass

        try:
            maybe = await self._gateway.get_historical_bars(
                q.tickers,
                q.from_,
                q.to,
                q.interval,
                q.page_size,
                max(0, (q.page - 1) * q.page_size),
            )
            return _normalize_gateway_return(maybe)
        except TypeError:
            pass

        maybe = await self._gateway.get_historical_bars(q)
        return _normalize_gateway_return(maybe)


# =============================================================================
# Cache compatibility (named vs positional TTL)
# =============================================================================


async def _cache_set_json_compat(
    cache: CachePort, key: str, value: dict[str, Any], *, ttl: int
) -> None:
    """Set JSON in cache, supporting both named and positional TTL signatures."""
    try:
        # Preferred: implementations that accept a named ttl
        await cache.set_json(key, value, ttl=ttl)
    except TypeError:
        # Some implementations only accept positional ttl — route through Any to appease mypy.
        cache_any = cast(Any, cache)
        await cache_any.set_json(key, value, ttl)


# =============================================================================
# Return normalization
# =============================================================================
def _normalize_gateway_return(
    maybe: Any,
) -> tuple[list[HistoricalBarDTO], int, str | None]:
    """Normalize gateway return into ``(items, total, etag_or_none)``."""
    if isinstance(maybe, dict):
        items = list(maybe.get("items", []))
        total = int(maybe.get("total", len(items)))
        etag = maybe.get("etag")
        return items, total, (etag or None)

    if isinstance(maybe, tuple) and len(maybe) == 3:
        items, total, etag = maybe
        return list(items), int(total), (etag or None)
    if isinstance(maybe, tuple) and len(maybe) == 2:
        items, total = maybe
        return list(items), int(total), None

    if isinstance(maybe, Iterable):
        items = list(maybe)
        return items, len(items), None

    raise TypeError("Unsupported gateway return type for historical bars")
