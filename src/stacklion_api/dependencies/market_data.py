# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Dependency wiring for Market Data (gateways, use cases).

Overview:
    Provides FastAPI dependency providers for Market Data, notably the
    :class:`GetHistoricalQuotesUseCase` consumed by the historical quotes router
    and the A5 latest-quotes use case used by `/v1/quotes`.

Layer:
    dependencies

Design:
    * Always return the **real** use case types (no fake UCs).
    * Select the gateway implementation by environment:
        - **Real Marketstack gateway** for production-like runs.
        - **Deterministic stub gateway** only when explicitly opted-in
          (ENVIRONMENT=test or STACKLION_TEST_MODE=1, or missing access key).
          This keeps tests hermetic without touching business logic.
    * Provide a minimal, concurrency-safe in-memory cache that implements
      :class:`CachePort` for dev/test. Swap to Redis in production wiring.

Notes:
    Metrics concerns (histograms, counters) are owned by the gateway/UC layers,
    not this dependency module. This keeps dependency code focused on wiring.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
from stacklion_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)

if TYPE_CHECKING:
    # Import only for static typing to avoid runtime dependency cycles in some test setups.
    from stacklion_api.application.use_cases.quotes.get_latest_quotes import GetLatestQuotesUseCase

__all__ = [
    "InMemoryAsyncCache",
    "get_historical_quotes_use_case",
    "get_latest_quotes_use_case",
    "get_quotes_uc",  # alias used by quotes_router
]

logger = logging.getLogger(__name__)

# Global settings are optional; fall back to ENV if unavailable.
try:  # pragma: no cover - optional dependency during unit tests
    from stacklion_api.config.settings import get_settings
except Exception:  # pragma: no cover - keep silent in CI
    get_settings = None  # type: ignore[assignment]


# =============================================================================
# Cache implementation
# =============================================================================
class InMemoryAsyncCache(CachePort):
    """A small, concurrency-safe in-memory cache for dev/test.

    This implements :class:`CachePort` and stores JSON-serializable payloads with
    per-key TTLs. Expiration is enforced lazily on read.

    Do not use in production; wire Redis (or another distributed cache) instead.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """Return a JSON blob by key if present and not expired.

        Args:
            key: Cache key.

        Returns:
            dict[str, Any] | None: The cached JSON object if present and fresh; otherwise ``None``.
        """
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            now = time.time()
            if expires_at and expires_at < now:
                # Lazy eviction
                self._store.pop(key, None)
                return None
            return value

    async def set_json(self, key: str, value: dict[str, Any], *, ttl: int) -> None:  # type: ignore[override]
        """Set a JSON blob by key with TTL.

        Args:
            key: Cache key.
            value: JSON-serializable mapping to store.
            ttl: Time-to-live in seconds.

        Returns:
            None
        """
        async with self._lock:
            expires_at = time.time() + max(0, int(ttl))
            self._store[key] = (expires_at, value)


# =============================================================================
# Marketstack settings loading
# =============================================================================
def _load_marketstack_settings() -> MarketstackSettings:
    """Load Marketstack settings from global Settings or environment.

    Returns:
        MarketstackSettings: Concrete settings for the Marketstack client.

    Behavior:
        * If ``get_settings()`` exists and exposes ``.marketstack``, those values are used.
        * Otherwise, falls back to environment variables:
            - ``MARKETSTACK_BASE_URL`` (default: https://api.marketstack.com/v1)
            - ``MARKETSTACK_ACCESS_KEY`` (empty if unset)
            - ``MARKETSTACK_TIMEOUT_S`` (default: 2.0)
            - ``MARKETSTACK_MAX_RETRIES`` (default: 0)
    """
    if callable(get_settings):
        try:
            settings = get_settings()
            ms = getattr(settings, "marketstack", None)
            if ms is not None:
                base_url = getattr(ms, "base_url", "https://api.marketstack.com/v1")
                access_key = getattr(ms, "access_key", SecretStr(""))
                timeout_s = float(getattr(ms, "timeout_s", 2.0))
                max_retries = int(getattr(ms, "max_retries", 0))
                return MarketstackSettings(
                    base_url=str(base_url),
                    access_key=(
                        access_key
                        if isinstance(access_key, SecretStr)
                        else SecretStr(str(access_key))
                    ),
                    timeout_s=timeout_s,
                    max_retries=max_retries,
                )
        except Exception as exc:  # pragma: no cover
            # Keep logs quiet in CI; we simply fall back to ENV.
            logger.debug("Falling back to ENV for Marketstack settings: %s", exc, exc_info=exc)

    base_url = os.getenv("MARKETSTACK_BASE_URL", "https://api.marketstack.com/v1")
    access_key = os.getenv("MARKETSTACK_ACCESS_KEY", "")
    timeout_s = float(os.getenv("MARKETSTACK_TIMEOUT_S", "2.0"))
    max_retries = int(os.getenv("MARKETSTACK_MAX_RETRIES", "0"))
    return MarketstackSettings(
        base_url=base_url,
        access_key=SecretStr(access_key),
        timeout_s=timeout_s,
        max_retries=max_retries,
    )


# =============================================================================
# Gateway selection (real vs deterministic stub)
# =============================================================================
def _is_deterministic_mode(settings: MarketstackSettings) -> bool:
    """Return True when the network-free deterministic gateway should be used.

    Deterministic mode is intended for hermetic tests and local dev when no access
    key is configured.

    Triggers:
        * ``ENVIRONMENT=test`` (pytest / router-only integration tests)
        * ``STACKLION_TEST_MODE=1``
        * Empty Marketstack access key

    Args:
        settings: Loaded Marketstack settings.

    Returns:
        bool: True if deterministic gateway should be used.
    """
    if os.getenv("ENVIRONMENT", "").lower() == "test":
        return True
    if os.getenv("STACKLION_TEST_MODE") == "1":
        return True
    return not (settings.access_key.get_secret_value() or "").strip()


def _build_real_gateway(settings: MarketstackSettings) -> MarketstackGateway:
    """Construct the real Marketstack gateway.

    Args:
        settings: Marketstack configuration.

    Returns:
        MarketstackGateway: Adapter gateway that uses an ``httpx.AsyncClient``.

    Notes:
        We pass a plain ``httpx.AsyncClient`` so that test frameworks (e.g., respx)
        can intercept outbound calls if desired.
    """
    client = httpx.AsyncClient(timeout=settings.timeout_s)
    return MarketstackGateway(client=client, settings=settings)


class DeterministicMarketDataGateway:
    """Deterministic, network-free gateway for hermetic tests.

    This adapter mirrors the essential shape of the real gateway for the A6 surface,
    returning a stable payload and a fixed weak ETag to enable 200/304 flows without
    external I/O.

    It returns one bar for the first requested ticker, within the requested date range.
    """

    def __init__(self, *, etag: str = 'W/"abc123"') -> None:
        """Initialize the deterministic gateway.

        Args:
            etag: Weak ETag value to emit for every response.
        """
        self.etag = etag

    async def get_historical_bars(
        self,
        *,
        tickers: Sequence[str],
        date_from: datetime,
        date_to: datetime,
        interval: BarInterval,
        limit: int,
        offset: int,
    ) -> tuple[list[HistoricalBarDTO], int, str]:
        """Return a deterministic historical bar set.

        Args:
            tickers: Requested symbol list.
            date_from: Start (inclusive).
            date_to: End (inclusive).
            interval: Bar interval (e.g., ``I1D`` or ``I1M``).
            limit: Page size.
            offset: Page offset.

        Returns:
            tuple[list[HistoricalBarDTO], int, str]: A tuple of (items, total, etag).

        Raises:
            MarketDataValidationError: If the time window is invalid.
        """
        if date_from > date_to:
            raise MarketDataValidationError("'from' must be <= 'to'")

        # Construct one synthetic bar deterministically.
        symbol = (tickers[0] if tickers else "AAPL").upper()
        bar_dt = min(date_to, datetime(2025, 1, 2, tzinfo=UTC))
        dto = HistoricalBarDTO(
            ticker=symbol,
            timestamp=bar_dt,
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
            interval=(
                interval if interval in (BarInterval.I1D, BarInterval.I1M) else BarInterval.I1D
            ),
        )
        total = 1
        items = [dto] if limit > 0 else []
        return items, total, self.etag


# =============================================================================
# Public providers
# =============================================================================
def get_historical_quotes_use_case() -> GetHistoricalQuotesUseCase:
    """Provide the use case for the historical quotes router.

    Selection logic:
        * If deterministic mode is enabled (explicitly for tests or no key),
          wire :class:`DeterministicMarketDataGateway` (network-free).
        * Otherwise, wire the real :class:`MarketstackGateway`.

    Returns:
        GetHistoricalQuotesUseCase: Fully wired use case instance.
    """
    cache: CachePort = InMemoryAsyncCache()
    ms_settings = _load_marketstack_settings()
    gateway = (
        DeterministicMarketDataGateway()
        if _is_deterministic_mode(ms_settings)
        else _build_real_gateway(ms_settings)
    )
    return GetHistoricalQuotesUseCase(cache=cache, gateway=gateway)


def get_latest_quotes_use_case() -> GetLatestQuotesUseCase:
    """Provide the (non-historical) latest quotes use case for `/v1/quotes`.

    Mirrors the historical provider: always returns the real use case type and
    selects the gateway implementation by environment.

    Returns:
        GetLatestQuotesUseCase: Fully wired latest-quotes use case instance.
    """
    # Imported lazily to avoid import cycles when the historical surface is optional.
    from stacklion_api.application.use_cases.quotes.get_latest_quotes import (
        GetLatestQuotesUseCase,
    )

    cache: CachePort = InMemoryAsyncCache()
    ms_settings = _load_marketstack_settings()
    gateway = (
        DeterministicMarketDataGateway()
        if _is_deterministic_mode(ms_settings)
        else _build_real_gateway(ms_settings)
    )
    return GetLatestQuotesUseCase(cache=cache, gateway=gateway)


def get_quotes_uc() -> GetLatestQuotesUseCase:
    """Compatibility alias used by `quotes_router`.

    Returns:
        GetLatestQuotesUseCase: Instance provided by :func:`get_latest_quotes_use_case`.
    """
    return get_latest_quotes_use_case()
