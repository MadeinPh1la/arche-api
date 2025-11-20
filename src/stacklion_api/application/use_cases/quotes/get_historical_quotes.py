# src/stacklion_api/application/use_cases/quotes/get_historical_quotes.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Get historical quotes.

Synopsis:
    Orchestrates fetching historical OHLCV data for one or more tickers,
    with an application-level cache in front of the market data gateway.

Responsibilities:
    * Validate and normalize query parameters.
    * Build a canonical cache key and TTL band based on interval.
    * Attempt cache read; on miss, call the gateway.
    * Cache successful pages (items + total + (weak) ETag).
    * Record UC-level and gateway-level latency metrics via Prometheus.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, cast

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.schemas.dto.quotes import (
    HistoricalBarDTO,
    HistoricalQueryDTO,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.infrastructure.caching.json_cache import (
    TTL_EOD_S,
    TTL_INTRADAY_RECENT_S,
)
from stacklion_api.infrastructure.observability.metrics_market_data import (
    observe_upstream_request,
    usecase_historical_quotes_latency_seconds,
)


class GetHistoricalQuotesUseCase:
    """Fetch historical OHLCV bars backed by a cache and market data gateway."""

    def __init__(self, *, cache: CachePort, gateway: Any) -> None:
        # We keep the gateway structurally typed (must expose get_historical_bars)
        # to support multiple historical signatures without over-constraining types.
        self._cache = cache
        self._gateway = gateway

    async def execute(
        self,
        q: HistoricalQueryDTO,
        *,
        if_none_match: str | None = None,
    ) -> tuple[list[HistoricalBarDTO], int, str]:
        """Execute the use case.

        Args:
            q: Query DTO describing tickers, date range, interval, and paging.
            if_none_match: Optional weak ETag supplied by the client.

        Returns:
            A tuple of (items, total_count, etag). ETag is always a string.
        """
        # Basic window validation – tests expect a MarketDataValidationError here.
        if q.from_ > q.to:
            raise MarketDataValidationError("from_ cannot be after to")

        with usecase_historical_quotes_latency_seconds.time():
            cache_key = self._cache_key(q)

            # Try cache first. If we have a hit and the client's ETag matches,
            # we can short-circuit at the controller layer with 304.
            cached = await self._cache_get_page(cache_key)
            if cached is not None:
                items, total, weak_etag = cached
                if weak_etag == if_none_match:
                    # Controller will turn this into a 304 Not Modified response.
                    return items, total, weak_etag
                return items, total, weak_etag

            # Cache miss – hit the gateway, and record gateway metrics.
            with observe_upstream_request(
                provider="marketstack",
                endpoint="historical_quotes",
                interval=str(q.interval),
            ) as obs:
                try:
                    items, total, provider_etag = await self._get_from_gateway(q)
                except Exception:
                    # Map any upstream failure into an error sample.
                    obs.mark_error("exception")
                    raise

            ttl = self._ttl_for_interval(q.interval)
            if provider_etag:
                weak_etag = _weak_etag(provider_etag)
            else:
                weak_etag = _compute_synthetic_weak_etag(items, total)

            await self._cache_set_page(cache_key, items, total, weak_etag, ttl=ttl)
            return items, total, weak_etag

    # ------------------------------------------------------------------ #
    # Cache key + TTL
    # ------------------------------------------------------------------ #
    def _cache_key(self, q: HistoricalQueryDTO) -> str:
        """Build a stable cache key tail for a historical query."""
        tickers_part = ",".join(sorted(q.tickers))
        from_part = q.from_.isoformat()
        to_part = q.to.isoformat()
        interval_part = str(q.interval)
        page_part = f"p{q.page}"
        size_part = f"s{q.page_size}"
        return (
            "historical:"
            f"{tickers_part}:"
            f"{interval_part}:"
            f"{from_part}:"
            f"{to_part}:"
            f"{page_part}:"
            f"{size_part}"
        )

    @staticmethod
    def _ttl_for_interval(interval: BarInterval) -> int:
        """Map interval → TTL band."""
        if interval == BarInterval.I1D:
            return TTL_EOD_S
        return TTL_INTRADAY_RECENT_S

    # ------------------------------------------------------------------ #
    # Cache helpers
    # ------------------------------------------------------------------ #
    async def _cache_get_page(
        self,
        key: str,
    ) -> tuple[list[HistoricalBarDTO], int, str] | None:
        """Fetch a cached page if present and decode DTOs.

        Returns:
            A tuple of (items, total, etag) if present, otherwise None.
            ETag is always normalized to a weak ETag string.
        """
        cached = await self._cache.get_json(key)
        if cached is None:
            return None

        try:
            items_raw = cast(list[dict[str, Any]], cached["items"])
            total = int(cached["total"])
            etag_raw = cached.get("etag")
        except (KeyError, TypeError, ValueError) as exc:
            # Cache contents are invalid – treat as logical corruption.
            raise MarketDataValidationError("Corrupt historical cache entry") from exc

        items = [_dto_from_dict(payload) for payload in items_raw]

        # If there is no stored ETag (legacy cache entries), compute one now.
        if etag_raw is None:
            etag = _compute_synthetic_weak_etag(items, total)
        else:
            etag = _weak_etag(str(etag_raw))

        return items, total, etag

    async def _cache_set_page(
        self,
        key: str,
        items: Iterable[HistoricalBarDTO],
        total: int,
        etag: str,
        *,
        ttl: int,
    ) -> None:
        """Serialize and store a page in the cache."""
        if ttl <= 0:
            return

        cache_obj: dict[str, Any] = {
            "items": [_dto_to_dict(dto) for dto in items],
            "total": int(total),
            "etag": etag,
        }

        await _cache_set_json_compat(self._cache, key, cache_obj, ttl=ttl)

    # ------------------------------------------------------------------ #
    # Gateway dispatch
    # ------------------------------------------------------------------ #
    async def _get_from_gateway(
        self,
        q: HistoricalQueryDTO,
    ) -> tuple[list[HistoricalBarDTO], int, str | None]:
        """Call the gateway, supporting several historical signature shapes.

        Supported patterns (in order of preference):

            1) get_historical_bars(q=HistoricalQueryDTO)
            2) get_historical_bars(
                   tickers=list[str],
                   date_from=datetime,
                   date_to=datetime,
                   interval=BarInterval,
                   limit=int,
                   offset=int,
               )
            3) get_historical_bars(
                   tickers, date_from, date_to, interval, limit, offset
               )
            4) get_historical_bars(HistoricalQueryDTO)
            5) get_historical_bars(...) returning:
               - (items, total)
               - (items, total, etag)
               - {"items": [...], "total": N} (+ optional "etag")
               - Iterable[HistoricalBarDTO | Mapping]

        Only ``TypeError`` is treated as a signature mismatch; any other
        exception propagates as a genuine failure.
        """
        offset = (q.page - 1) * q.page_size

        # 1) q= keyword – used by SimpleGateway in tests.
        try:
            maybe = await self._gateway.get_historical_bars(q=q)
            return _normalize_gateway_return(maybe)
        except TypeError:
            pass

        # 2) Named-argument signature – preferred for real gateways.
        try:
            maybe = await self._gateway.get_historical_bars(
                tickers=q.tickers,
                date_from=q.from_,
                date_to=q.to,
                interval=q.interval,
                limit=q.page_size,
                offset=offset,
            )
            return _normalize_gateway_return(maybe)
        except TypeError:
            pass

        # 3) Positional 6-arg signature – used by _PositionalGateway test stub.
        try:
            maybe = await self._gateway.get_historical_bars(
                q.tickers,
                q.from_,
                q.to,
                q.interval,
                q.page_size,
                offset,
            )
            return _normalize_gateway_return(maybe)
        except TypeError:
            pass

        # 4) DTO positional fallback – works for gateways that just want the DTO.
        maybe = await self._gateway.get_historical_bars(q)
        return _normalize_gateway_return(maybe)


# ---------------------------------------------------------------------- #
# Cache JSON compatibility helper
# ---------------------------------------------------------------------- #


async def _cache_set_json_compat(
    cache: CachePort,
    key: str,
    value: dict[str, Any],
    *,
    ttl: int,
) -> None:
    """Set JSON in cache, supporting both named and positional TTL signatures.

    Some test doubles expose ``set_json(key, value, ttl)`` (positional),
    while the real Redis cache uses a keyword-only ``ttl`` parameter.
    """
    try:
        # Preferred: implementations that accept a named ttl kwarg.
        await cache.set_json(key, value, ttl=ttl)
    except TypeError:
        # Fallback: positional ttl – used only by specific test doubles.
        cache_any = cast(Any, cache)
        await cache_any.set_json(key, value, ttl)


# ---------------------------------------------------------------------- #
# DTO (de)serialization helpers
# ---------------------------------------------------------------------- #


def _dto_to_dict(dto: HistoricalBarDTO) -> dict[str, Any]:
    """Convert HistoricalBarDTO to a JSON-ready dict (but not JSON string)."""
    # Pydantic v2 models expose model_dump(); use JSON mode to avoid raw
    # datetime/Decimal objects that json.dumps cannot serialize.
    model_dump = getattr(dto, "model_dump", None)
    raw = model_dump(mode="json") if callable(model_dump) else dict(dto)

    # Ensure we use the enum value, not the enum instance.
    interval = raw.get("interval")
    if isinstance(interval, BarInterval):
        raw["interval"] = interval.value

    return cast(dict[str, Any], raw)


def _dto_from_dict(data: dict[str, Any]) -> HistoricalBarDTO:
    """Rebuild HistoricalBarDTO from a dict recovered from cache."""
    return HistoricalBarDTO(**data)


def _normalize_gateway_return(
    value: Any,
) -> tuple[list[HistoricalBarDTO], int, str | None]:
    """Normalize different gateway return shapes to a canonical tuple.

    Allowed shapes:
        - (items, total)
        - (items, total, etag)
        - {"items": [...], "total": N} (+ optional "etag")
        - Iterable[HistoricalBarDTO | Mapping]  (total inferred as len)
    """
    # Dict form: {"items": [...], "total": N, "etag": "..."}.
    if isinstance(value, dict):
        try:
            items_raw = value["items"]
            total_raw = value["total"]
        except KeyError as exc:
            raise MarketDataValidationError(
                "Gateway dict must contain 'items' and 'total'",
            ) from exc
        etag_raw = value.get("etag")
        items = _normalize_items(items_raw)
        return items, int(total_raw), cast(str | None, etag_raw)

    # Tuple form: (items, total[, etag]).
    if isinstance(value, tuple):
        if len(value) == 2:
            items_raw, total_raw = value
            etag_raw = None
        elif len(value) == 3:
            items_raw, total_raw, etag_raw = value
        else:
            raise MarketDataValidationError(
                "Gateway must return (items, total) or (items, total, etag)",
            )
        items = _normalize_items(items_raw)
        return items, int(total_raw), cast(str | None, etag_raw)

    # Iterable form (list, generator, etc.) – treat as items only.
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        items = _normalize_items(value)
        return items, len(items), None

    raise MarketDataValidationError(
        "Gateway returned unexpected type for historical bars",
    )


def _normalize_items(raw: Any) -> list[HistoricalBarDTO]:
    """Normalize gateway items into a list of HistoricalBarDTO."""
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        raise MarketDataValidationError("Gateway items must be an iterable of DTOs or dicts")

    items: list[HistoricalBarDTO] = []
    for item in raw:
        if isinstance(item, HistoricalBarDTO):
            items.append(item)
        elif isinstance(item, dict):
            items.append(_dto_from_dict(item))
        else:
            raise MarketDataValidationError("Gateway items must be DTOs or dicts")
    return items


def _compute_synthetic_weak_etag(
    items: Iterable[HistoricalBarDTO],
    total: int,
) -> str:
    """Compute a deterministic weak ETag from page contents.

    Used when the upstream provider does not supply its own ETag
    or when cache entries pre-date ETag support.
    """
    payload = {
        "items": [_dto_to_dict(dto) for dto in items],
        "total": int(total),
    }
    # Stable, compact JSON to feed into the hash.
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return f'W/"{digest}"'


def _weak_etag(provider_etag: str) -> str:
    """Normalize provider ETag to a weak ETag suitable for HTTP layer."""
    # If provider already returns a weak ETag, keep it; otherwise prefix.
    if provider_etag.startswith('W/"') or provider_etag.startswith("W/'"):
        return provider_etag
    return f'W/"{provider_etag}"'
