# src/stacklion_api/infrastructure/external_apis/marketstack/client.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Marketstack Transport Client (Option A).

Synopsis:
    Thin, framework-agnostic HTTP client for Marketstack that:
      * Builds query parameters for EOD & intraday requests.
      * Performs asynchronous HTTP with timeouts.
      * Maps HTTP/transport errors to domain exceptions.
      * Returns raw provider JSON plus upstream ETag (if present).

Design:
    - Transport-only: no DTO mapping, caching, metrics, or business logic.
    - Deterministic error mapping:
        429 → MarketDataRateLimited
        402 → MarketDataQuotaExceeded
        400/422 → MarketDataBadRequest
        timeouts/network/5xx → MarketDataUnavailable
        non-JSON or unexpected shape → MarketDataValidationError
    - Normalizes symbols to uppercase to avoid downstream drift.

Layer:
    infrastructure/external_apis
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


class MarketstackClient:
    """Asynchronous transport client for Marketstack.

    This client is the source of truth for outbound HTTP to Marketstack. It
    performs network I/O, enforces timeouts, and translates errors to domain
    exceptions. It **does not** parse payloads into DTOs—mapping belongs in the
    adapter gateway.

    Args:
        http: Shared :class:`httpx.AsyncClient` with connection pooling.
        settings: Provider configuration (base URL, access key, timeout).
    """

    def __init__(self, http: httpx.AsyncClient, settings: MarketstackSettings) -> None:
        self._http = http
        self._cfg = settings

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    async def eod(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        page: int,
        limit: int,
    ) -> tuple[dict[str, Any], str | None]:
        """Fetch **End-of-Day** bars as raw JSON plus upstream ETag.

        Args:
            tickers: Ticker symbols (case-insensitive); joined by commas.
            date_from: Inclusive start date in ``YYYY-MM-DD``.
            date_to: Inclusive end date in ``YYYY-MM-DD``.
            page: 1-based page number (>= 1).
            limit: Page size (>= 1).

        Returns:
            tuple[dict[str, Any], str | None]: ``(raw_json, etag)`` where
            ``raw_json`` contains at least ``{"data": [...]}`` and optionally
            ``"pagination"``, and ``etag`` is the upstream ETag if present.

        Raises:
            MarketDataValidationError: Invalid pagination or unexpected payload shape.
            MarketDataBadRequest: Upstream 400/422 parameter error.
            MarketDataQuotaExceeded: Upstream 402 quota exceeded.
            MarketDataRateLimited: Upstream 429 rate-limited.
            MarketDataUnavailable: Timeout, network failure, or non-4xx HTTP error.
        """
        if page < 1 or limit < 1:
            raise MarketDataValidationError("invalid pagination parameters")

        params = self._params_eod(
            tickers=_normalize_symbols(tickers),
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=(page - 1) * limit,
        )
        url = f"{self._cfg.base_url}/eod"
        return await self._get(url, params)

    async def intraday(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        interval: str,
        page: int,
        limit: int,
    ) -> tuple[dict[str, Any], str | None]:
        """Fetch **intraday** bars as raw JSON plus upstream ETag.

        Args:
            tickers: Ticker symbols (case-insensitive); joined by commas.
            date_from: Inclusive start instant (ISO-8601, UTC recommended).
            date_to: Inclusive end instant (ISO-8601, UTC recommended).
            interval: Bar interval string accepted by Marketstack (e.g., ``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``).
            page: 1-based page number (>= 1).
            limit: Page size (>= 1).

        Returns:
            tuple[dict[str, Any], str | None]: ``(raw_json, etag)`` where
            ``raw_json`` contains at least ``{"data": [...]}`` and optionally
            ``"pagination"``, and ``etag`` is the upstream ETag if present.

        Raises:
            MarketDataValidationError: Invalid pagination or unexpected payload shape.
            MarketDataBadRequest: Upstream 400/422 parameter error.
            MarketDataQuotaExceeded: Upstream 402 quota exceeded.
            MarketDataRateLimited: Upstream 429 rate-limited.
            MarketDataUnavailable: Timeout, network failure, or non-4xx HTTP error.
        """
        if page < 1 or limit < 1:
            raise MarketDataValidationError("invalid pagination parameters")

        params = self._params_intraday(
            tickers=_normalize_symbols(tickers),
            date_from=date_from,
            date_to=date_to,
            interval=interval,
            limit=limit,
            offset=(page - 1) * limit,
        )
        url = f"{self._cfg.base_url}/intraday"
        return await self._get(url, params)

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    def _params_base(self) -> dict[str, str]:
        """Return base query parameters containing the access key.

        Returns:
            dict[str, str]: Mapping with ``access_key`` set.
        """
        return {"access_key": self._cfg.access_key.get_secret_value()}

    def _params_eod(
        self, *, tickers: list[str], date_from: str, date_to: str, limit: int, offset: int
    ) -> dict[str, Any]:
        """Construct query parameters for the EOD endpoint.

        Args:
            tickers: Uppercased ticker symbols.
            date_from: Inclusive start date (``YYYY-MM-DD``).
            date_to: Inclusive end date (``YYYY-MM-DD``).
            limit: Page size.
            offset: Zero-based offset.

        Returns:
            dict[str, Any]: Query mapping for ``/eod``.
        """
        return {
            **self._params_base(),
            "symbols": ",".join(tickers),
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit,
            "offset": offset,
        }

    def _params_intraday(
        self,
        *,
        tickers: list[str],
        date_from: str,
        date_to: str,
        interval: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        """Construct query parameters for the intraday endpoint.

        Args:
            tickers: Uppercased ticker symbols.
            date_from: Inclusive start instant (ISO-8601).
            date_to: Inclusive end instant (ISO-8601).
            interval: Bar interval string accepted by Marketstack.
            limit: Page size.
            offset: Zero-based offset.

        Returns:
            dict[str, Any]: Query mapping for ``/intraday``.
        """
        return {
            **self._params_base(),
            "symbols": ",".join(tickers),
            "date_from": date_from,
            "date_to": date_to,
            "interval": interval,
            "limit": limit,
            "offset": offset,
        }

    async def _get(self, url: str, params: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Execute a GET and return raw JSON and ETag with strict error mapping.

        Args:
            url: Fully qualified endpoint URL.
            params: Query parameters to send.

        Returns:
            tuple[dict[str, Any], str | None]: The provider JSON payload and the upstream ETag.

        Raises:
            MarketDataBadRequest: Upstream 400/422 parameter error.
            MarketDataQuotaExceeded: Upstream 402 quota exceeded.
            MarketDataRateLimited: Upstream 429 rate-limited.
            MarketDataUnavailable: Timeout, network failure, or non-4xx HTTP error.
            MarketDataValidationError: Non-JSON or unexpected payload shape.
        """
        try:
            # Small explicit User-Agent aids observability and vendor-side debugging.
            headers = {"User-Agent": "stacklion-api/marketstack-client"}
            resp = await self._http.get(
                url, params=params, headers=headers, timeout=self._cfg.timeout_s
            )

            # Explicitly handle empty 204s (unexpected for these endpoints).
            if resp.status_code == 204:
                raise MarketDataValidationError("empty provider response (204)")

            # Classify common 4xx explicitly before generic handler.
            if resp.status_code == 429:
                raise MarketDataRateLimited("upstream rate limit exceeded")
            if resp.status_code in (400, 422):
                raise MarketDataBadRequest("invalid upstream parameters")
            if resp.status_code == 402:
                raise MarketDataQuotaExceeded("provider quota exceeded")

            resp.raise_for_status()

            try:
                raw = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise MarketDataValidationError("invalid provider response (non-JSON)") from exc

            if not isinstance(raw, dict) or "data" not in raw:
                raise MarketDataValidationError("unexpected provider payload")

            etag = _extract_etag(resp)
            return raw, etag

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MarketDataUnavailable("market data provider unavailable") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if 400 <= code < 500:
                raise MarketDataBadRequest("invalid upstream parameters") from exc
            raise MarketDataUnavailable("market data provider unavailable") from exc


# ------------------------------------------------------------------------- #
# Module utilities                                                          #
# ------------------------------------------------------------------------- #


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    """Normalize symbols once (uppercase/strip) to avoid downstream drift.

    Args:
        symbols: Raw symbols as provided by callers.

    Returns:
        list[str]: Uppercased, de-blanked symbols.
    """
    return [s.strip().upper() for s in symbols if str(s).strip()]


def _extract_etag(resp: httpx.Response) -> str | None:
    """Extract an upstream ETag header value, case-insensitively.

    Args:
        resp: HTTP response.

    Returns:
        str | None: The ETag value if present, otherwise ``None``.
    """
    return resp.headers.get("ETag") or resp.headers.get("Etag") or resp.headers.get("etag")


__all__ = ["MarketstackClient"]
