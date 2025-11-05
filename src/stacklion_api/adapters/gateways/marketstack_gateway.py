# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Adapter Gateway: Marketstack → Application DTOs (Option A).

Synopsis:
    Mapping-only gateway that converts Marketstack payloads into application DTOs.
    Supports two client shapes:
      1) Transport client exposing ``.eod()`` / ``.intraday()``, and
      2) Raw ``httpx.AsyncClient`` (tests), with local URL/param build.

Responsibilities:
    * Validate minimal provider payload shape (pagination + ``data`` list).
    * Coerce types safely; raise domain validation on bad values.
    * Deterministic mapping of transport/HTTP errors to domain exceptions.

Layer:
    adapters/gateways
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from stacklion_api.application.schemas.dto.quotes import (
    HistoricalBarDTO,
    HistoricalQueryDTO,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


class MarketstackGateway:
    """Gateway that maps Marketstack responses to application DTOs."""

    def __init__(self, client: Any, settings: MarketstackSettings | None = None) -> None:
        """Initialize the gateway.

        Args:
            client: Either a transport client exposing ``.eod()`` / ``.intraday()`` or an
                ``httpx.AsyncClient`` used for raw requests.
            settings: Marketstack settings; required when using a raw ``httpx.AsyncClient``.
        """
        self._client = client
        self._settings = settings

    def _require_settings(self) -> MarketstackSettings:
        """Return settings or raise if not configured.

        Returns:
            MarketstackSettings: Non-null settings.

        Raises:
            MarketDataValidationError: When settings are missing for raw HTTP mode.
        """
        if self._settings is None:
            raise MarketDataValidationError(
                "gateway_not_configured", details={"missing": "MarketstackSettings"}
            )
        return self._settings

    @staticmethod
    def _validate_list_payload(raw: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """Validate provider payload and extract rows + total."""
        data = raw.get("data")
        if not isinstance(data, list):
            raise MarketDataValidationError("bad_shape", details={"expected": "data:list"})
        total = 0
        pg = raw.get("pagination")
        if isinstance(pg, Mapping) and isinstance(pg.get("total"), int):
            total = pg["total"]
        return data, total

    @staticmethod
    def _coerce_bar(x: Mapping[str, Any], interval_obj: BarInterval) -> HistoricalBarDTO:
        """Coerce a provider row to a :class:`HistoricalBarDTO`."""
        try:
            ticker = str(x["symbol"]).upper()
            ts = datetime.fromisoformat(str(x["date"]).replace("Z", "+00:00")).astimezone(UTC)
            open_ = Decimal(str(x["open"]))
            high = Decimal(str(x["high"]))
            low = Decimal(str(x["low"]))
            close = Decimal(str(x["close"]))
            volume = int(x["volume"])
        except Exception as e:  # noqa: BLE001
            raise MarketDataValidationError("bad_values", details={"error": str(e)}) from e
        return HistoricalBarDTO(
            ticker=ticker,
            timestamp=ts,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            interval=interval_obj,
        )

    async def _transport_eod(
        self, *, tickers: Sequence[str], date_from: str, date_to: str, page: int, limit: int
    ) -> tuple[Mapping[str, Any], str | None]:
        """Call the EOD endpoint via transport or raw HTTP."""
        if hasattr(self._client, "eod"):
            return await self._client.eod(
                tickers=tickers, date_from=date_from, date_to=date_to, page=page, limit=limit
            )
        settings = self._require_settings()
        params = {
            "symbols": ",".join(tickers),
            "access_key": settings.access_key.get_secret_value(),
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
            "offset": (page - 1) * limit,
        }
        r = await self._client.get(f"{settings.base_url}/eod", params=params)
        return await self._handle_httpx_response(r)

    async def _transport_intraday(
        self,
        *,
        tickers: Sequence[str],
        date_from_iso: str,
        date_to_iso: str,
        interval: str,
        page: int,
        limit: int,
    ) -> tuple[Mapping[str, Any], str | None]:
        """Call the intraday endpoint via transport or raw HTTP."""
        if hasattr(self._client, "intraday"):
            return await self._client.intraday(
                tickers=tickers,
                date_from=date_from_iso,
                date_to=date_to_iso,
                interval=interval,
                page=page,
                limit=limit,
            )
        settings = self._require_settings()
        params = {
            "symbols": ",".join(tickers),
            "access_key": settings.access_key.get_secret_value(),
            "date_from": date_from_iso,
            "date_to": date_to_iso,
            "interval": interval,
            "limit": limit,
            "offset": (page - 1) * limit,
        }
        r = await self._client.get(f"{settings.base_url}/intraday", params=params)
        return await self._handle_httpx_response(r)

    async def _handle_httpx_response(
        self, r: httpx.Response
    ) -> tuple[Mapping[str, Any], str | None]:
        """Map HTTP errors to domain exceptions and parse JSON."""
        status = r.status_code
        if status == 429:
            raise MarketDataRateLimited()
        if status == 402:
            raise MarketDataQuotaExceeded()
        if status in (400, 422):
            raise MarketDataBadRequest()
        if status >= 500:
            raise MarketDataUnavailable()
        try:
            payload: Mapping[str, Any] = r.json()
        except Exception as e:  # noqa: BLE001
            raise MarketDataValidationError("non_json", details={"error": str(e)}) from e
        etag = r.headers.get("ETag")
        return payload, etag

    async def get_historical_bars(
        self, q: HistoricalQueryDTO
    ) -> tuple[list[HistoricalBarDTO], int]:
        """Fetch and map historical bars for the given query."""
        tickers = [t.upper() for t in q.tickers]
        interval_obj = q.interval
        interval_value = getattr(q.interval, "value", str(q.interval)).lower()
        is_daily = interval_value == "1d"

        if is_daily:
            raw, _etag = await self._transport_eod(
                tickers=tickers,
                date_from=q.from_.date().isoformat(),
                date_to=q.to.date().isoformat(),
                page=q.page,
                limit=q.page_size,
            )
        else:
            raw, _etag = await self._transport_intraday(
                tickers=tickers,
                date_from_iso=q.from_.isoformat(),
                date_to_iso=q.to.isoformat(),
                interval=interval_value,
                page=q.page,
                limit=q.page_size,
            )

        data, total = self._validate_list_payload(raw)
        items = [self._coerce_bar(x, interval_obj) for x in data]
        return items, total
