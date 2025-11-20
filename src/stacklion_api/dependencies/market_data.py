# src/stacklion_api/dependencies/market_data.py

# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Dependency wiring for Market Data (gateways, use cases).

Overview:
    Provides FastAPI dependency providers for Market Data, notably the
    :class:`GetHistoricalQuotesUseCase` consumed by the historical quotes router
    and the A5 latest-quotes use case used by `/v2/quotes`.

Layer:
    dependencies

Design:
    * Always return the real use case types (no fake UCs).
    * Select the gateway implementation by environment:
        - Real Marketstack gateway for production-like runs.
        - Deterministic in-memory gateway for CI/tests and when no API key.
    * Select cache implementation by environment:
        - In-memory async cache in tests (hermetic, no Redis dependency).
        - RedisJsonCache in non-test environments.
    * Keep configuration deterministic via Settings when appropriate, but avoid
      cross-test bleed by not caching Settings inside test-oriented helpers.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

import httpx
from pydantic import SecretStr

from stacklion_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.infrastructure.caching.json_cache import RedisJsonCache
from stacklion_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)

logger = logging.getLogger(__name__)


def get_settings() -> Any:
    """Shim for tests to patch settings resolution in this module.

    By default, dynamically imports the canonical `get_settings()` from the
    config module. Tests monkeypatch `dependencies.market_data.get_settings`
    to inject fake settings without touching the global Settings cache.
    """
    from stacklion_api.config.settings import get_settings as core_get_settings

    return core_get_settings()


# =============================================================================
# Marketstack settings adapter
# =============================================================================


def _load_marketstack_settings() -> MarketstackSettings:
    """Load Marketstack settings from canonical Settings.

    Returns:
        MarketstackSettings: Concrete settings for the Marketstack client.

    Behavior:
        * Always use this module's `get_settings` shim.
        * In tests, `dependencies.market_data.get_settings` is monkeypatched, so
          this function will consume the fake settings object instead of the
          real application Settings.
    """
    # Import this module under its canonical name so we hit the monkeypatched attribute.
    import stacklion_api.dependencies.market_data as md

    settings = md.get_settings()
    base_url = getattr(settings, "marketstack_base_url", None) or "https://api.marketstack.com/v2"
    access_key_raw = getattr(settings, "marketstack_api_key", None) or ""
    timeout_s = float(getattr(settings, "marketstack_timeout_s", 2.0))
    max_retries = int(getattr(settings, "marketstack_max_retries", 0))

    return MarketstackSettings(
        base_url=str(base_url),
        access_key=SecretStr(str(access_key_raw)),
        timeout_s=timeout_s,
        max_retries=max_retries,
    )


# =============================================================================
# Gateway selection (real vs deterministic stub)
# =============================================================================


def _is_deterministic_mode(settings: MarketstackSettings) -> bool:
    """Return True when the network-free deterministic gateway should be used.

    Deterministic mode is intended for hermetic tests and local dev when no access
    key is configured, or when explicitly flagged via test environment variables.

    Triggers:
        * ENVIRONMENT=test
        * STACKLION_TEST_MODE=1
        * Empty Marketstack access key (no key means we must not hit the network).

    Args:
        settings: Loaded Marketstack settings.

    Returns:
        bool: True if deterministic gateway should be used.
    """
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    key = (settings.access_key.get_secret_value() or "").strip()

    # Explicit test environments always select deterministic mode.
    if env == "test" or os.getenv("STACKLION_TEST_MODE") == "1":
        return True

    # No key: we cannot talk to the real API, so fall back to deterministic gateway.
    return not key  # real key + no explicit test flags => use real gateway


def _build_real_gateway(settings: MarketstackSettings) -> MarketstackGateway:
    """Construct the real Marketstack gateway.

    Args:
        settings: Concrete Marketstack settings.

    Returns:
        MarketstackGateway: Fully configured gateway instance.

    Raises:
        MarketDataValidationError: If configuration is invalid.
    """
    key = (settings.access_key.get_secret_value() or "").strip()
    if not key:
        raise MarketDataValidationError("Marketstack access key is required for real gateway")

    client = httpx.AsyncClient(
        base_url=settings.base_url,
        timeout=settings.timeout_s,
    )
    return MarketstackGateway(client=client, settings=settings)


# =============================================================================
# Deterministic in-memory gateway for tests/dev
# =============================================================================


@dataclass(frozen=True)
class _DeterministicBar:
    """Simple value object representing a deterministic historical bar."""

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class DeterministicMarketDataGateway:
    """Deterministic, in-memory MarketData gateway for tests and local dev.

    Supports:
        * Keyword signature:
              get_historical_bars(
                  tickers=...,
                  date_from=...,
                  date_to=...,
                  interval=...,
                  limit=...,
                  offset=...,
              )
        * Positional signature:
              get_historical_bars(tickers, date_from, date_to, interval, limit, offset)
        * DTO-based signature:
              get_historical_bars(HistoricalQueryDTO(...))

    Returns:
        tuple[list[HistoricalBarDTO], int, str | None]: (items, total, etag)
    """

    def __init__(self) -> None:
        self._store: dict[str, list[_DeterministicBar]] = {}

    async def get_historical_bars(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[list[HistoricalBarDTO], int, str | None]:
        """Return a deterministic series of bars."""
        tickers: Sequence[str]
        date_from: datetime
        date_to: datetime
        interval: BarInterval
        limit: int
        offset: int

        if kwargs:
            # Keyword signature
            try:
                tickers = cast(Sequence[str], kwargs["tickers"])
                date_from = cast(datetime, kwargs["date_from"])
                date_to = cast(datetime, kwargs["date_to"])
                interval = cast(BarInterval, kwargs["interval"])
                limit = int(kwargs.get("limit", 50))
                offset = int(kwargs.get("offset", 0))
            except KeyError as exc:  # pragma: no cover
                msg = f"Missing argument for deterministic gateway: {exc}"
                raise TypeError(msg) from exc
        elif len(args) == 1:
            # DTO-style call: get_historical_bars(dto)
            q = cast(Any, args[0])
            try:
                tickers = cast(Sequence[str], q.tickers)
                date_from = cast(datetime, q.from_)
                date_to = cast(datetime, q.to)
                interval = cast(BarInterval, q.interval)
                limit = int(q.page_size)
                page = int(q.page)
                offset = max(0, (page - 1) * limit)
            except AttributeError as exc:  # pragma: no cover
                msg = f"Unsupported DTO passed to deterministic gateway: {exc}"
                raise TypeError(msg) from exc
        elif len(args) >= 5:
            # Positional signature: tickers, date_from, date_to, interval, limit, [offset]
            tickers = cast(Sequence[str], args[0])
            date_from = cast(datetime, args[1])
            date_to = cast(datetime, args[2])
            interval = cast(BarInterval, args[3])
            limit = int(args[4])
            offset = int(args[5]) if len(args) > 5 else 0
        else:  # pragma: no cover
            raise TypeError("Insufficient arguments for deterministic gateway")

        if date_from > date_to:
            raise MarketDataValidationError("date_from must be <= date_to")

        key = f"{','.join(sorted(tickers))}:{interval.value}:{date_from.isoformat()}:{date_to.isoformat()}"
        bars = self._store.get(key)
        if bars is None:
            # Single-bar deterministic series: close=1.5 to match tests.
            mid = date_from
            bars = [
                _DeterministicBar(
                    ts=mid,
                    open=Decimal("1.0"),
                    high=Decimal("2.0"),
                    low=Decimal("0.5"),
                    close=Decimal("1.5"),
                    volume=Decimal("10"),
                )
            ]
            self._store[key] = bars

        window = bars[offset : offset + limit] if limit > 0 else []
        ticker_value = tickers[0].upper() if tickers else "DET"
        items = [
            HistoricalBarDTO(
                ticker=ticker_value,
                timestamp=bar.ts,
                interval=interval,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in window
        ]
        total = len(bars)
        etag = 'W/"deterministic-etag"'
        return items, total, etag


# =============================================================================
# Cache implementations
# =============================================================================


class InMemoryAsyncCache(CachePort):
    """A small, concurrency-safe in-memory cache for dev/test."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get_json(self, key: str) -> Mapping[str, Any] | None:
        """Return a JSON blob by key if present and not expired."""
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            now = asyncio.get_event_loop().time()
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            return value

    async def set_json(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        ttl: int,
    ) -> None:
        """Store a JSON-serializable mapping under the given key."""
        now = asyncio.get_event_loop().time()
        expires_at = now if ttl <= 0 else now + float(ttl)

        async with self._lock:
            self._store[key] = (expires_at, dict(value))

    async def get_raw(self, key: str) -> bytes | None:
        """Read a raw bytes payload by key."""
        obj = await self.get_json(key)
        if obj is None:
            return None
        return json.dumps(obj).encode("utf-8")

    async def set_raw(self, key: str, value: bytes, ttl: int) -> None:
        """Store raw bytes by key."""
        try:
            decoded = json.loads(value.decode("utf-8"))
        except Exception:  # pragma: no cover
            decoded = {"raw": value.decode("utf-8", errors="ignore")}
        await self.set_json(key, decoded, ttl=ttl)


def _build_cache() -> CachePort:
    """Select cache backend based on environment.

    - ENVIRONMENT=test or STACKLION_TEST_MODE=1 → InMemoryAsyncCache
    - otherwise → RedisJsonCache
    """
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    if env == "test" or os.getenv("STACKLION_TEST_MODE") == "1":
        return InMemoryAsyncCache()

    try:
        return RedisJsonCache(namespace="stacklion:market_data:v1")
    except Exception:  # pragma: no cover - hard fallback if Redis misconfigured
        logger.exception("Falling back to InMemoryAsyncCache due to Redis init failure")
        return InMemoryAsyncCache()


# =============================================================================
# Historical quotes use case dependency
# =============================================================================


async def get_historical_quotes_use_case() -> AsyncGenerator[GetHistoricalQuotesUseCase, None]:
    """Yield a configured GetHistoricalQuotesUseCase instance.

    This is a FastAPI dependency used by the historical quotes router.

    Yields:
        GetHistoricalQuotesUseCase: Configured use case instance.
    """
    cache: CachePort = _build_cache()
    ms_settings = _load_marketstack_settings()
    gateway: Any = (
        DeterministicMarketDataGateway()
        if _is_deterministic_mode(ms_settings)
        else _build_real_gateway(ms_settings)
    )
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gateway)
    try:
        yield uc
    finally:
        # Real gateway owns an AsyncClient; deterministic gateway does not.
        if isinstance(gateway, MarketstackGateway) and hasattr(gateway, "client"):
            try:
                await gateway.client.aclose()
            except Exception:  # pragma: no cover
                logger.exception("error closing Marketstack HTTP client")


# =============================================================================
# Latest quotes (A5 surface) dependency
# =============================================================================


def _resolve_get_quotes_use_case_cls() -> type[Any]:
    """Resolve the get-quotes use case class from the application module.

    Tries a couple of likely class names to stay resilient to minor refactors.
    Raises RuntimeError if no suitable class is found.
    """
    module = importlib.import_module("stacklion_api.application.use_cases.quotes.get_quotes")
    for name in ("GetQuotesUseCase", "GetQuotes"):
        cls = getattr(module, name, None)
        if cls is not None:
            return cast(type[Any], cls)
    msg = "Could not resolve GetQuotes use case class from get_quotes.py"
    raise RuntimeError(msg)


def get_latest_quotes_use_case() -> Any:
    """Construct the latest quotes use case instance.

    Returns:
        Any: Configured latest quotes use case instance.
    """
    cache: CachePort = _build_cache()
    ms_settings = _load_marketstack_settings()
    gateway: Any = (
        DeterministicMarketDataGateway()
        if _is_deterministic_mode(ms_settings)
        else _build_real_gateway(ms_settings)
    )
    use_case_cls = _resolve_get_quotes_use_case_cls()
    return use_case_cls(gateway=gateway, cache=cache)


def get_quotes_uc() -> Any:
    """Compatibility alias used by `quotes_router`.

    Returns:
        Any: Instance provided by :func:`get_latest_quotes_use_case`.
    """
    return get_latest_quotes_use_case()
