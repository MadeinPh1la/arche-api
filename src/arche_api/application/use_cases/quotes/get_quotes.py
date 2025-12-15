# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Use Case: Get Latest Quotes.

Purpose:
    Orchestrate retrieval of latest quotes via the market data gateway and
    return DTOs for presentation. Optionally uses a read-through cache for
    hot latest quotes.

Layer:
    application/use_cases
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from arche_api.application.interfaces.cache_port import CachePort
from arche_api.application.schemas.dto.quotes import QuoteDTO, QuotesBatchDTO
from arche_api.domain.entities.quote import Quote
from arche_api.domain.exceptions.market_data import MarketDataUnavailable
from arche_api.domain.interfaces.gateways.market_data_gateway import (
    MarketDataGatewayProtocol,
)

# Default TTL for hot latest quotes (seconds). Kept in the application layer
# to avoid a hard dependency on infrastructure caching modules.
# Tests expect a very short TTL for "hot" quotes.
TTL_QUOTE_HOT_S = 5


def _quote_cache_key(ticker: str) -> str:
    """Build the cache key for a latest quote.

    Args:
        ticker: Ticker symbol.

    Returns:
        Cache key string for the given ticker.
    """
    return f"quote:{ticker.upper()}"


def _quote_to_cache_payload(q: Quote) -> dict[str, Any]:
    """Serialize a :class:`Quote` into a cache-friendly mapping.

    Args:
        q: Domain quote entity.

    Returns:
        Mapping suitable for JSON cache storage.
    """
    as_of = q.as_of.isoformat() if q.as_of is not None else None
    return {
        "ticker": q.ticker,
        "price": str(q.price),
        "currency": q.currency,
        "as_of": as_of,
        "volume": q.volume,
    }


def _payload_to_quote_dto(payload: dict[str, Any]) -> QuoteDTO:
    """Reconstitute a QuoteDTO from cached payload.

    Args:
        payload: Mapping previously produced by `_quote_to_cache_payload`.

    Returns:
        Reconstructed QuoteDTO.
    """
    from datetime import datetime

    as_of_raw = payload.get("as_of")
    as_of = datetime.fromisoformat(as_of_raw) if as_of_raw else None

    return QuoteDTO(
        ticker=str(payload["ticker"]),
        price=Decimal(str(payload["price"])),
        currency=str(payload["currency"]),
        as_of=as_of,
        volume=payload.get("volume"),
    )


class GetQuotes:
    """Use case to fetch latest quotes with optional read-through caching.

    Args:
        gateway: Market data gateway implementation that can return latest quotes
            for a collection of symbols.
        cache: Optional cache port used to store and retrieve hot latest quotes.

    Raises:
        MarketDataUnavailable: If the gateway does not expose any compatible
            latest-quotes method or the provider is effectively unavailable.
    """

    def __init__(
        self,
        gateway: MarketDataGatewayProtocol,
        cache: CachePort | None = None,
    ) -> None:
        """Initialize the GetQuotes use case.

        Args:
            gateway: Market data gateway implementation.
            cache: Optional cache implementation for hot latest quotes.
        """
        self._gateway = gateway
        self._cache = cache

    async def execute(self, tickers: Sequence[str]) -> QuotesBatchDTO:
        """Fetch latest quotes for the given tickers.

        Args:
            tickers: Sequence of ticker symbols (case-insensitive).

        Returns:
            QuotesBatchDTO containing quotes in the deterministic order of the
            input `tickers` sequence.
        """
        normalized = [t.upper() for t in tickers]

        # ---------------------- Non-cached path ---------------------- #
        if self._cache is None or not normalized:
            quotes = await self._fetch_latest(normalized)
            dtos = [self._to_dto(q) for q in quotes]
            # Ensure deterministic order of input.
            by_symbol = {dto.ticker: dto for dto in dtos}
            ordered_items = [by_symbol[s] for s in normalized if s in by_symbol]
            return QuotesBatchDTO(items=ordered_items)

        # ---------------------- Cached path ---------------------- #
        cache = self._cache
        cached_dtos: dict[str, QuoteDTO] = {}
        missing: list[str] = []

        # 1. Fan-out reads for each ticker.
        for symbol in normalized:
            key = _quote_cache_key(symbol)
            payload = await cache.get_json(key)
            if payload is None:
                missing.append(symbol)
                continue
            cached_dtos[symbol] = _payload_to_quote_dto(dict(payload))

        # 2. Fetch missing tickers from gateway in a single shot.
        fresh_dtos: dict[str, QuoteDTO] = {}
        if missing:
            fresh_quotes: list[Quote] = await self._fetch_latest(missing)
            for q in fresh_quotes:
                dto = self._to_dto(q)
                symbol = dto.ticker.upper()
                fresh_dtos[symbol] = dto
                key = _quote_cache_key(symbol)
                await cache.set_json(
                    key,
                    _quote_to_cache_payload(q),
                    ttl=TTL_QUOTE_HOT_S,
                )

        # 3. Merge cached + fresh, respecting input order.
        result_items: list[QuoteDTO] = []
        for symbol in normalized:
            if symbol in fresh_dtos:
                result_items.append(fresh_dtos[symbol])
            elif symbol in cached_dtos:
                result_items.append(cached_dtos[symbol])

        return QuotesBatchDTO(items=result_items)

    async def _fetch_latest(self, symbols: Sequence[str]) -> list[Quote]:
        """Call the underlying gateway using the best-available method.

        This shields the use case from concrete gateway method naming drift.

        Args:
            symbols: Sequence of ticker symbols to fetch.

        Returns:
            List of domain `Quote` entities.

        Raises:
            MarketDataUnavailable: If the gateway does not expose a usable
                latest-quotes method.
        """
        gw = self._gateway

        # Preferred, protocol-aligned method.
        if hasattr(gw, "get_latest_quotes"):
            return await gw.get_latest_quotes(symbols)

        # Common alternates used in some gateways.
        if hasattr(gw, "get_latest"):
            return await gw.get_latest(symbols)  # type: ignore[no-any-return]

        if hasattr(gw, "get_intraday_latest_bars"):
            return await gw.get_intraday_latest_bars(symbols)  # type: ignore[no-any-return]

        if hasattr(gw, "get_quotes"):
            return await gw.get_quotes(symbols)  # type: ignore[no-any-return]

        # If we get here, the gateway wiring is simply wrong for this UC.
        raise MarketDataUnavailable(
            "Market data gateway does not implement a latest-quotes method "
            "compatible with GetQuotes.",
        )

    @staticmethod
    def _to_dto(q: Quote) -> QuoteDTO:
        """Map a domain Quote to a DTO.

        Args:
            q: Domain quote entity.

        Returns:
            QuoteDTO containing the projected fields.
        """
        return QuoteDTO(
            ticker=q.ticker,
            price=Decimal(str(q.price)),
            currency=q.currency,
            as_of=q.as_of,
            volume=q.volume,
        )
