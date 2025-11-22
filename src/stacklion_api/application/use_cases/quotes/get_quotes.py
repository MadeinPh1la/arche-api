# src/stacklion_api/application/use_cases/quotes/get_quotes.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Use Case: Get Latest Quotes

Purpose:
    Orchestrate retrieval of latest quotes via market data gateway and
    return DTOs for presentation. Optionally uses a read-through cache for
    hot latest quotes.

Layer: application/use_cases
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.schemas.dto.quotes import QuoteDTO, QuotesBatchDTO
from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.exceptions.market_data import MarketDataUnavailable
from stacklion_api.domain.interfaces.gateways.market_data_gateway import (
    MarketDataGatewayProtocol,
)
from stacklion_api.infrastructure.caching.json_cache import TTL_QUOTE_HOT_S


def _quote_cache_key(ticker: str) -> str:
    """Build the tail cache key for a latest quote."""
    return f"quote:{ticker.upper()}"


def _quote_to_cache_payload(q: Quote) -> dict[str, Any]:
    """Serialize a :class:`Quote` into a cache-friendly mapping."""
    as_of = q.as_of.isoformat() if q.as_of is not None else None
    return {
        "ticker": q.ticker,
        "price": str(q.price),
        "currency": q.currency,
        "as_of": as_of,
        "volume": q.volume,
    }


def _payload_to_quote_dto(payload: dict[str, Any]) -> QuoteDTO:
    """Reconstitute a QuoteDTO from cached payload."""
    # Import here to avoid circulars if DTO module grows.
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
    """Use case to fetch latest quotes.

    Args:
        gateway: Market data gateway implementation.
        cache: Optional cache implementation for hot latest quotes.

    Raises:
        MarketDataUnavailable: If provider is down or improperly configured.
    """

    def __init__(
        self,
        gateway: MarketDataGatewayProtocol,
        cache: CachePort | None = None,
    ) -> None:
        self._gateway = gateway
        self._cache = cache

    async def execute(self, tickers: Sequence[str]) -> QuotesBatchDTO:
        """Fetch latest quotes.

        Args:
            tickers: Sequence of ticker symbols.

        Returns:
            QuotesBatchDTO: Quotes in deterministic order of input.
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
                await cache.set_json(key, _quote_to_cache_payload(q), ttl=TTL_QUOTE_HOT_S)

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
            "Market data gateway does not implement a latest-quotes method compatible with GetQuotes.",
        )

    @staticmethod
    def _to_dto(q: Quote) -> QuoteDTO:
        """Map a domain Quote to a DTO."""
        return QuoteDTO(
            ticker=q.ticker,
            price=Decimal(str(q.price)),
            currency=q.currency,
            as_of=q.as_of,
            volume=q.volume,
        )
