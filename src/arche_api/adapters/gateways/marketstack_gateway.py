# src/arche_api/adapters/gateways/marketstack_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Adapter Gateway: Marketstack → application ingest + read mapping (V2).

This gateway sits on top of the V2 transport client and provides:

* Ingest port for intraday bars (provider-agnostic record format).
* Read helper for historical bars mapping to read-side DTOs.
* Latest-quote helper for live quote use cases.

Design principles:
    * Optionally fail fast on intervals outside your plan via an allow-list.
    * Normalize short interval aliases (e.g., "1m" → "1min", "1h" → "1h").
    * Validate provider payloads deterministically; surface provider errors verbatim.
    * Preserve numeric precision (strings) on ingest records to avoid drift.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from arche_api.application.interfaces.market_data_gateway import (
    IntradayBarRecord,
    MarketDataGateway,
)
from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.domain.entities.historical_bar import BarInterval
from arche_api.domain.entities.quote import Quote
from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from arche_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


class MarketstackGateway(MarketDataGateway):
    """Marketstack adapter implementing the ingest port and read helpers."""

    def __init__(self, client: Any, settings: MarketstackSettings | None = None) -> None:
        """Initialize the gateway.

        Args:
            client: Transport client exposing ``.eod()`` / ``.intraday()`` or an
                ``httpx.AsyncClient`` used directly for tests.
            settings: Provider settings. Required when using a raw ``httpx.AsyncClient``.
        """
        self._client = client
        self._settings = settings

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #
    def _require_settings(self) -> MarketstackSettings:
        """Return settings or raise for raw HTTP mode.

        Returns:
            MarketstackSettings: The configured settings.

        Raises:
            MarketDataValidationError: If settings are required but missing.
        """
        if self._settings is None:
            raise MarketDataValidationError(
                "gateway_not_configured",
                details={"missing": "MarketstackSettings"},
            )
        return self._settings

    def _allowed_intervals(self) -> set[str]:
        """Return the plan-allowed intraday intervals (lowercased).

        If no explicit allow-list is configured via environment, this returns an
        empty set and no plan-level gating is applied at the gateway. This keeps
        the default behavior backward-compatible and lets the provider enforce
        any defaults unless you explicitly opt in via env.
        """
        if self._settings is None:
            return set()

        # Only enforce a plan allow-list when explicitly configured via env.
        raw = self._settings.allowed_intraday_intervals_raw
        if not raw:
            return set()

        return {s.strip().lower() for s in self._settings.allowed_intraday_intervals}

    @staticmethod
    def _normalize_interval(interval: str) -> str:
        """Normalize a caller interval into a V2-accepted provider label.

        Accepts shorthand forms (e.g., ``"1m"``, ``"5m"``, ``"1h"``) and returns
        the canonical provider labels (e.g., ``"1min"``, ``"5min"``, ``"1h"``).

        Args:
            interval: The caller-supplied interval.

        Returns:
            The normalized interval string (V2-accepted).
        """
        s = interval.strip().lower()
        mapping: dict[str, str] = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "60m": "1h",
            "1hour": "1h",
        }
        # Already canonical V2 labels.
        if s in {"1min", "5min", "15min", "30min", "1h"}:
            return s
        return mapping.get(s, s)

    def _enforce_plan_interval(self, normalized: str) -> str:
        """Fail fast if the interval is not allowed by the configured plan.

        Args:
            normalized: Normalized provider interval label.

        Returns:
            The validated interval (unchanged).

        Raises:
            MarketDataBadRequest: If the interval is outside the configured allow-list.
        """
        allowed = self._allowed_intervals()
        if allowed and normalized not in allowed:
            raise MarketDataBadRequest(
                details={
                    "code": "interval_not_allowed_on_plan",
                    "message": (
                        f"Interval '{normalized}' not available on current plan. "
                        f"Use one of: {sorted(allowed)}"
                    ),
                },
            )
        return normalized

    @staticmethod
    def _format_intraday_timestamp(dt: datetime) -> str:
        """Format a datetime into a Marketstack V2 intraday-compatible string.

        Marketstack documents acceptable formats as:

        * YYYY-MM-DD
        * YYYY-MM-DD HH:MM:SS
        * ISO-8601: ``YYYY-MM-DDTHH:MM:SSO`` (e.g. ``2025-11-12T20:03:47+0000``)

        We normalize to ISO-8601 with numeric UTC offset and no microseconds.

        Args:
            dt: Datetime instance (any tz).

        Returns:
            A string formatted as ``YYYY-MM-DDTHH:MM:SS+0000``.
        """
        dt_utc = dt.astimezone(UTC).replace(microsecond=0)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%S%z")

    @staticmethod
    def _validate_list_payload(raw: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """Validate provider JSON payload and extract rows + total.

        Args:
            raw: Parsed provider payload.

        Returns:
            A tuple ``(rows, total)`` where ``rows`` is the provider ``data`` list
            and ``total`` is the pagination total (0 if absent).

        Raises:
            MarketDataValidationError: If the shape is unexpected or if the provider
            returned a structured error (``{"error": {...}}``).
        """
        err = raw.get("error")
        if isinstance(err, Mapping):
            code = err.get("code")
            msg = err.get("message")
            raise MarketDataValidationError(
                "provider_error",
                details={"code": code, "message": msg},
            )

        data = raw.get("data")
        if not isinstance(data, list):
            raise MarketDataValidationError(
                "bad_shape",
                details={"expected": "data:list"},
            )

        total = 0
        pg = raw.get("pagination")
        if isinstance(pg, Mapping) and isinstance(pg.get("total"), int):
            total = pg["total"]

        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise MarketDataValidationError(
                    "bad_shape",
                    details={"expected": "data:list[object]"},
                )
            rows.append(item)
        return rows, total

    @staticmethod
    def _coerce_bar_to_dto(x: Mapping[str, Any], interval_obj: BarInterval) -> HistoricalBarDTO:
        """Convert a provider row to a read-side :class:`HistoricalBarDTO`.

        Args:
            x: Provider row mapping.
            interval_obj: Domain interval enum for the DTO.

        Returns:
            An initialized :class:`HistoricalBarDTO`.

        Raises:
            MarketDataValidationError: On missing/malformed values.
        """
        try:
            ticker = str(x["symbol"]).upper()
            ts = datetime.fromisoformat(str(x["date"]).replace("Z", "+00:00")).astimezone(UTC)
            open_ = Decimal(str(x["open"]))
            high = Decimal(str(x["high"]))
            low = Decimal(str(x["low"]))
            close = Decimal(str(x["close"]))
            volume = int(x["volume"])
        except Exception as exc:  # noqa: BLE001
            raise MarketDataValidationError(
                "bad_values",
                details={"error": str(exc)},
            ) from exc

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

    @staticmethod
    def _coerce_bar_to_record(x: Mapping[str, Any]) -> IntradayBarRecord:
        """Convert a provider row to a provider-agnostic ingest record.

        Numeric values are kept as strings to avoid precision loss.

        Args:
            x: Provider row mapping.

        Returns:
            A normalized :class:`IntradayBarRecord`.

        Raises:
            MarketDataValidationError: On missing/malformed values.
        """
        try:
            symbol = str(x["symbol"]).upper()
            ts = (
                datetime.fromisoformat(str(x["date"]).replace("Z", "+00:00"))
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
            return IntradayBarRecord(
                symbol=symbol,
                ts=ts,
                open=str(x["open"]),
                high=str(x["high"]),
                low=str(x["low"]),
                close=str(x["close"]),
                volume=str(x["volume"]),
            )
        except Exception as exc:  # noqa: BLE001
            raise MarketDataValidationError(
                "bad_values",
                details={"error": str(exc)},
            ) from exc

    @staticmethod
    def _row_to_quote(symbol: str, ts: datetime, row: Mapping[str, Any]) -> Quote:
        """Convert a provider EOD row into a Quote entity.

        Args:
            symbol: Uppercase symbol that this row belongs to.
            ts: Parsed timestamp for the bar.
            row: Provider row mapping.

        Returns:
            A Quote domain entity.

        Raises:
            MarketDataValidationError: On malformed price/currency/volume values.
        """
        try:
            price = Decimal(str(row["close"]))
        except Exception as exc:  # noqa: BLE001
            raise MarketDataValidationError(
                "bad_values",
                details={"error": str(exc)},
            ) from exc

        currency = str(row.get("currency") or "USD")
        volume_raw = row.get("volume")
        volume: int | None
        try:
            volume = int(volume_raw) if volume_raw is not None else None
        except (TypeError, ValueError):
            volume = None

        return Quote(
            ticker=symbol,
            price=price,
            currency=currency,
            as_of=ts,
            volume=volume,
        )

    def _select_latest_eod_by_symbol(
        self,
        rows: Sequence[Mapping[str, Any]],
        tickers: Sequence[str],
    ) -> dict[str, tuple[datetime, Mapping[str, Any]]]:
        """Select the most recent EOD bar per requested symbol.

        Args:
            rows: Provider data rows from an EOD response.
            tickers: Requested ticker symbols (case-insensitive).

        Returns:
            Mapping from uppercase symbol → (timestamp, provider row).
        """
        requested = {s.upper() for s in tickers if s}
        latest: dict[str, tuple[datetime, Mapping[str, Any]]] = {}

        for row in rows:
            symbol_raw = row.get("symbol")
            if not symbol_raw:
                continue
            sym = str(symbol_raw).upper()
            if sym not in requested:
                continue

            date_raw = row.get("date")
            try:
                ts = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00")).astimezone(UTC)
            except (TypeError, ValueError):
                # Skip rows with malformed dates; provider bug, not caller error.
                continue

            existing = latest.get(sym)
            if existing is None or ts > existing[0]:
                latest[sym] = (ts, row)

        return latest

    async def _handle_httpx_response(
        self,
        response: httpx.Response,
    ) -> tuple[Mapping[str, Any], str | None]:
        """Map HTTP errors to domain exceptions and parse JSON for raw HTTP mode.

        Args:
            response: Provider HTTP response.

        Returns:
            A tuple ``(payload, etag)``.

        Raises:
            MarketDataRateLimited: On 429.
            MarketDataQuotaExceeded: On 402.
            MarketDataBadRequest: On 401/403/400/422 with parsed provider details.
            MarketDataUnavailable: On 5xx.
            MarketDataValidationError: On non-JSON payloads.
        """
        status = response.status_code
        if status == 429:
            raise MarketDataRateLimited()
        if status == 402:
            raise MarketDataQuotaExceeded()
        if status in (401, 403, 400, 422):
            try:
                body: Any = response.json()
            except Exception:
                body = {}
            err = body.get("error") if isinstance(body, dict) else None
            details: dict[str, Any] = {"status": status}
            if isinstance(err, Mapping):
                details.update({"code": err.get("code"), "message": err.get("message")})
            raise MarketDataBadRequest(details=details)
        if status >= 500:
            raise MarketDataUnavailable()

        try:
            payload: Mapping[str, Any] = response.json()
        except Exception as exc:  # noqa: BLE001
            raise MarketDataValidationError(
                "non_json",
                details={"error": str(exc)},
            ) from exc

        etag = response.headers.get("ETag")
        return payload, etag

    async def _transport_eod(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        page: int,
        limit: int,
    ) -> tuple[Mapping[str, Any], str | None]:
        """Call the EOD endpoint via transport or raw HTTP (test path).

        Adapts transport client shape ``(payload, etag)`` → ``(payload, etag)`` and
        raw ``httpx.AsyncClient`` responses into the same tuple.
        """
        # Preferred path: fully-hardened transport client.
        if hasattr(self._client, "eod"):
            payload, etag = await self._client.eod(
                tickers=tickers,
                date_from=date_from,
                date_to=date_to,
                page=page,
                limit=limit,
            )
            return payload, etag

        # Raw HTTP path (used by unit tests).
        settings = self._require_settings()
        params = {
            "symbols": ",".join(tickers),
            "access_key": settings.access_key.get_secret_value(),
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
            "offset": (page - 1) * limit,
        }
        try:
            response = await self._client.get(f"{settings.base_url}/eod", params=params)
        except httpx.RequestError as exc:
            # Map network/transport failures into domain space.
            raise MarketDataUnavailable() from exc
        return await self._handle_httpx_response(response)

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
        """Call the intraday endpoint via transport or raw HTTP (test path).

        Adapts transport client shape ``(payload, etag)`` → ``(payload, etag)`` and
        raw ``httpx.AsyncClient`` responses into the same tuple. Applies interval
        normalization (and optional plan gating) before making the provider request.
        """
        normalized = self._normalize_interval(interval)
        normalized = self._enforce_plan_interval(normalized)

        # Preferred path: fully-hardened transport client.
        if hasattr(self._client, "intraday"):
            payload, etag = await self._client.intraday(
                tickers=tickers,
                date_from=date_from_iso,
                date_to=date_to_iso,
                interval=normalized,
                page=page,
                limit=limit,
            )
            return payload, etag

        # Raw HTTP path (used by unit tests).
        settings = self._require_settings()
        params = {
            "symbols": ",".join(tickers),
            "access_key": settings.access_key.get_secret_value(),
            "date_from": date_from_iso,
            "date_to": date_to_iso,
            "interval": normalized,
            "limit": limit,
            "offset": (page - 1) * limit,
        }
        try:
            response = await self._client.get(f"{settings.base_url}/intraday", params=params)
        except httpx.RequestError as exc:
            raise MarketDataUnavailable() from exc
        return await self._handle_httpx_response(response)

    # --------------------------------------------------------------------- #
    # Latest quotes helper (for GetQuotes use case)
    # --------------------------------------------------------------------- #
    async def get_latest_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        """Return latest quotes for the given symbols using EOD data.

        This method implements the "latest quotes" surface expected by the
        GetQuotes use case:

            - Fetches a recent EOD window for all requested symbols in a single call.
            - Picks the most recent bar per symbol by timestamp.
            - Maps each bar into a Quote domain entity.

        Args:
            symbols: Sequence of ticker symbols.

        Returns:
            A list of Quote entities, in no particular order. Missing symbols
            are simply omitted from the result.
        """
        tickers = [s.upper() for s in symbols if s]
        if not tickers:
            return []

        today = datetime.now(tz=UTC).date()
        start = today - timedelta(days=5)

        raw, _etag = await self._transport_eod(
            tickers=tickers,
            date_from=start.isoformat(),
            date_to=today.isoformat(),
            page=1,
            limit=100,
        )
        rows, _total = self._validate_list_payload(raw)

        latest_by_symbol = self._select_latest_eod_by_symbol(rows, tickers)

        quotes: list[Quote] = []
        for sym in tickers:
            entry = latest_by_symbol.get(sym)
            if entry is None:
                continue
            ts, row = entry
            quotes.append(self._row_to_quote(sym, ts, row))

        return quotes

    # --------------------------------------------------------------------- #
    # Ingest Port Implementation
    # --------------------------------------------------------------------- #
    async def fetch_intraday_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        page_size: int = 100,
    ) -> tuple[list[IntradayBarRecord], dict[str, Any]]:
        """Fetch intraday bars and return normalized ingest records.

        Args:
            symbol: Symbol (ticker).
            start: Inclusive start (UTC).
            end: Exclusive end (UTC).
            interval: Provider interval label (short or long form).
            page_size: Requested page size (V2 accepts up to ~100 per page).

        Returns:
            A tuple ``(records, meta)`` where ``records`` is a list of
            :class:`IntradayBarRecord` and ``meta`` may include ``etag``.
        """
        tickers = [symbol.upper()]
        raw, etag = await self._transport_intraday(
            tickers=tickers,
            date_from_iso=self._format_intraday_timestamp(start),
            date_to_iso=self._format_intraday_timestamp(end),
            interval=interval,
            page=1,
            limit=min(100, page_size),  # v2 intraday typically caps at ~100
        )
        data, _total = self._validate_list_payload(raw)
        records = [self._coerce_bar_to_record(x) for x in data]
        meta: dict[str, Any] = {}
        if etag:
            meta["etag"] = etag
        return records, meta

    # --------------------------------------------------------------------- #
    # Read-side helper for existing UCs/routers
    # --------------------------------------------------------------------- #
    async def get_historical_bars(
        self,
        q: HistoricalQueryDTO,
    ) -> tuple[list[HistoricalBarDTO], int]:
        """Fetch and map historical bars for read use-cases.

        Args:
            q: Read-side query object including symbols, interval, and window.

        Returns:
            A tuple ``(items, total)`` where ``items`` contains
            :class:`HistoricalBarDTO` objects, and ``total`` is pagination total.

        Raises:
            MarketDataValidationError: On unexpected payload shapes/values.
        """
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
                date_from_iso=self._format_intraday_timestamp(q.from_),
                date_to_iso=self._format_intraday_timestamp(q.to),
                interval=interval_value,
                page=q.page,
                limit=min(100, q.page_size),
            )

        data, total = self._validate_list_payload(raw)
        items = [self._coerce_bar_to_dto(x, interval_obj) for x in data]
        return items, total
