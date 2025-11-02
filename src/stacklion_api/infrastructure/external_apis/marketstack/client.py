# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Marketstack Gateway.

Async gateway to Marketstack with timeouts, bounded retries, strict schema
validation, precise domain error translation, and observability metrics.
Supports latest quotes and historical OHLCV bars (EOD / intraday).

This adapter is framework-agnostic and adheres to the gateway protocol in the
domain layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from stacklion_api.application.schemas.dto.quotes import (
    HistoricalBarDTO,
    HistoricalQueryDTO,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from stacklion_api.infrastructure.observability.metrics_market_data import (
    market_data_errors_total,
    market_data_success_total,
    stacklion_market_data_gateway_latency_seconds,
)


class MarketstackGateway(MarketDataGatewayProtocol):
    """Marketstack-backed market data gateway."""

    def __init__(self, client: httpx.AsyncClient, settings: MarketstackSettings) -> None:
        """Initialize the gateway.

        Args:
            client: Shared asynchronous HTTP client.
            settings: Provider configuration (base URL, access key, timeouts, retries).
        """
        self._client = client
        self._cfg = settings

    # -----------------------------------------------------------------------
    # Helpers: parameter builders
    # -----------------------------------------------------------------------

    def _params_latest(self, tickers: Sequence[str]) -> dict[str, str | int]:
        """Build query parameters for the 'latest' endpoint.

        Args:
            tickers: One or more ticker symbols.

        Returns:
            dict: Query parameter mapping (access key, symbols, limit).
        """
        return {
            "access_key": self._cfg.access_key.get_secret_value(),
            "symbols": ",".join(tickers),
            "limit": len(tickers),
        }

    def _params_eod(
        self, *, tickers: Sequence[str], date_from: str, date_to: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """Build query parameters for the EOD endpoint.

        Args:
            tickers: One or more ticker symbols.
            date_from: Inclusive start date (``YYYY-MM-DD``).
            date_to: Inclusive end date (``YYYY-MM-DD``).
            limit: Page size.
            offset: Zero-based offset.

        Returns:
            dict: Query parameter mapping.
        """
        return {
            "access_key": self._cfg.access_key.get_secret_value(),
            "symbols": ",".join(tickers),
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
            "offset": offset,
        }

    def _params_intraday(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        interval: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """Build query parameters for the intraday endpoint.

        Args:
            tickers: One or more ticker symbols.
            date_from: Inclusive start instant (ISO-8601, UTC).
            date_to: Inclusive end instant (ISO-8601, UTC).
            interval: Bar interval string (e.g., ``"1m"``, ``"5m"``).
            limit: Page size.
            offset: Zero-based offset.

        Returns:
            dict: Query parameter mapping.
        """
        return {
            "access_key": self._cfg.access_key.get_secret_value(),
            "symbols": ",".join(tickers),
            "date_from": date_from,
            "date_to": date_to,
            "interval": interval,
            "limit": limit,
            "offset": offset,
        }

    # -----------------------------------------------------------------------
    # Latest quotes
    # -----------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(MarketDataUnavailable),
        wait=wait_random_exponential(multiplier=0.1, max=1.0),
        stop=stop_after_attempt(1),
        reraise=True,
    )
    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        """Return latest quotes for the provided tickers.

        This method maps the provider payload to :class:`Quote` entities,
        translating shape issues and provider absences to domain exceptions.

        Args:
            tickers: Ticker symbols.

        Returns:
            list[Quote]: Latest quotes ordered by the provider response order.

        Raises:
            MarketDataUnavailable: On timeout/network/5xx with retry policy.
            MarketDataValidationError: On unexpected payload shape/values.
            SymbolNotFound: When provider returns no items for the symbols.
        """
        url = f"{self._cfg.base_url}/intraday/latest"
        attempts = 0
        params = self._params_latest(tickers)

        while True:
            attempts += 1
            t0 = monotonic()
            try:
                r = await self._client.get(url, params=params, timeout=self._cfg.timeout_s)
                r.raise_for_status()
                raw: dict[str, Any] = r.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                # Record latency even on errors.
                elapsed = monotonic() - t0
                stacklion_market_data_gateway_latency_seconds.labels(
                    "marketstack", "latest", "latest"
                ).observe(elapsed)
                if attempts <= self._cfg.max_retries:
                    raise MarketDataUnavailable("market data provider unavailable") from e
                raise MarketDataUnavailable("market data provider unavailable") from e
            except Exception as e:
                elapsed = monotonic() - t0
                stacklion_market_data_gateway_latency_seconds.labels(
                    "marketstack", "latest", "latest"
                ).observe(elapsed)
                raise MarketDataValidationError("invalid provider response") from e

            # Success path: record latency, then parse.
            elapsed = monotonic() - t0
            stacklion_market_data_gateway_latency_seconds.labels(
                "marketstack", "latest", "latest"
            ).observe(elapsed)

            try:
                if (
                    not isinstance(raw, dict)
                    or "data" not in raw
                    or not isinstance(raw["data"], list)
                ):
                    raise MarketDataValidationError("unexpected provider payload")

                data = raw["data"]
                items: list[Quote] = []
                for row in data:
                    sym = str(row["symbol"]).upper()
                    price = Decimal(str(row["last"]))
                    ts = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")).astimezone(
                        UTC
                    )
                    cur = str(row.get("currency") or "USD")
                    vol = row.get("volume")
                    vol_int = int(vol) if vol is not None else None
                    items.append(
                        Quote(ticker=sym, price=price, currency=cur, as_of=ts, volume=vol_int)
                    )

                if not items:
                    raise SymbolNotFound("no quotes for requested symbols")

                market_data_success_total.labels("marketstack", "latest").inc()
                return items

            except SymbolNotFound:
                # 2-label signature: (reason, endpoint)
                market_data_errors_total.labels("not_found", "latest").inc()
                raise
            except Exception as e:
                market_data_errors_total.labels("validation", "latest").inc()
                raise MarketDataValidationError("unexpected provider payload") from e

    # -----------------------------------------------------------------------
    # Historical OHLCV bars
    # -----------------------------------------------------------------------

    # ruff: noqa: C901
    @retry(
        retry=retry_if_exception_type(MarketDataUnavailable),
        wait=wait_random_exponential(multiplier=0.1, max=1.0),
        stop=stop_after_attempt(1),
        reraise=True,
    )
    async def get_historical_bars(
        self, q: HistoricalQueryDTO
    ) -> tuple[list[HistoricalBarDTO], int]:
        """Return historical OHLCV bars (EOD or intraday) with pagination.

        Args:
            q: Validated query DTO (tickers, from_, to, interval, page, page_size).

        Returns:
            tuple[list[HistoricalBarDTO], int]: Items and total available count.

        Raises:
            MarketDataUnavailable: On network errors and unavailability.
            MarketDataBadRequest: On upstream 4xx parameter issues.
            MarketDataRateLimited: On upstream rate limit (429).
            MarketDataQuotaExceeded: On upstream quota/plan exceeded (e.g., 402).
            MarketDataValidationError: On shape/semantic mapping failures.
        """
        if q.page < 1 or q.page_size < 1:
            raise MarketDataValidationError("invalid pagination parameters")
        offset = (q.page - 1) * q.page_size
        interval_label = (
            q.interval.value if isinstance(q.interval, BarInterval) else str(q.interval)
        )

        if q.interval == BarInterval.I1D:
            url = f"{self._cfg.base_url}/eod"
            endpoint = "eod"
            params = self._params_eod(
                tickers=q.tickers,
                date_from=q.from_.date().isoformat(),
                date_to=q.to.date().isoformat(),
                limit=q.page_size,
                offset=offset,
            )
        else:
            url = f"{self._cfg.base_url}/intraday"
            endpoint = "intraday"
            params = self._params_intraday(
                tickers=q.tickers,
                date_from=q.from_.isoformat(),
                date_to=q.to.isoformat(),
                interval=q.interval.value,
                limit=q.page_size,
                offset=offset,
            )

        attempts = 0
        while True:
            attempts += 1
            t0 = monotonic()
            try:
                r = await self._client.get(url, params=params, timeout=self._cfg.timeout_s)

                # CLASSIFY EARLY 4xx WITHOUT RAISING YET, BUT ALWAYS RECORD LATENCY
                elapsed = monotonic() - t0
                stacklion_market_data_gateway_latency_seconds.labels(
                    "marketstack", endpoint, interval_label
                ).observe(elapsed)

                if r.status_code == 429:
                    market_data_errors_total.labels("rate_limited", endpoint).inc()
                    raise MarketDataRateLimited("upstream rate limit exceeded")
                if r.status_code in (400, 422):
                    market_data_errors_total.labels("bad_request", endpoint).inc()
                    raise MarketDataBadRequest("invalid upstream parameters")
                if r.status_code in (402,):
                    market_data_errors_total.labels("quota_exceeded", endpoint).inc()
                    raise MarketDataQuotaExceeded("provider quota exceeded")

                r.raise_for_status()
                raw: dict[str, Any] = r.json()

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                # Record latency on network/timeout as well
                elapsed = monotonic() - t0
                stacklion_market_data_gateway_latency_seconds.labels(
                    "marketstack", endpoint, interval_label
                ).observe(elapsed)

                market_data_errors_total.labels("unavailable", endpoint).inc()
                if attempts <= self._cfg.max_retries:
                    raise MarketDataUnavailable("market data provider unavailable") from e
                raise MarketDataUnavailable("market data provider unavailable") from e

            except httpx.HTTPStatusError as e:
                # Already observed latency above for the HTTP call
                code = e.response.status_code if e.response is not None else 0
                if 400 <= code < 500:
                    market_data_errors_total.labels("bad_request", endpoint).inc()
                    raise MarketDataBadRequest("invalid upstream parameters") from e
                market_data_errors_total.labels("unavailable", endpoint).inc()
                raise MarketDataUnavailable("market data provider unavailable") from e

            # IMPORTANT: Domain exceptions must propagate unchanged.
            except (MarketDataRateLimited, MarketDataBadRequest, MarketDataQuotaExceeded):
                raise

            except Exception as e:
                # Parsing/shape errors after a response was received; latency was observed
                market_data_errors_total.labels("validation", endpoint).inc()
                raise MarketDataValidationError("invalid provider response") from e

            # Parse & validate payload
            try:
                if (
                    not isinstance(raw, dict)
                    or "data" not in raw
                    or not isinstance(raw["data"], list)
                ):
                    raise MarketDataValidationError("unexpected provider payload")

                data = raw["data"]
                pagination = raw.get("pagination", {}) or {}
                total = int(pagination.get("total", len(data)))

                items: list[HistoricalBarDTO] = []
                for row in data:
                    sym = str(row["symbol"]).upper()
                    ts = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")).astimezone(
                        UTC
                    )
                    open_ = Decimal(str(row["open"]))
                    high = Decimal(str(row["high"]))
                    low = Decimal(str(row["low"]))
                    close = Decimal(str(row["close"]))
                    vol_raw = row.get("volume")
                    vol = Decimal(str(vol_raw)) if vol_raw is not None else None

                    items.append(
                        HistoricalBarDTO(
                            ticker=sym,
                            timestamp=ts,
                            open=open_,
                            high=high,
                            low=low,
                            close=close,
                            volume=vol,
                            interval=q.interval,
                        )
                    )

                market_data_success_total.labels("marketstack", interval_label).inc()
                return items, total

            except Exception as e:
                market_data_errors_total.labels("validation", endpoint).inc()
                raise MarketDataValidationError("unexpected provider payload") from e
