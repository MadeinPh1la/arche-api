# src/stacklion_api/infrastructure/external_apis/marketstack/client.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Marketstack Transport Client (V2) — resilient, instrumented, async.

This transport is framework-agnostic and provides:

* Async HTTP (httpx) with per-request timeout.
* Jittered exponential retries (bounded); honors ``Retry-After`` seconds.
* Circuit breaker (CLOSED ↔ OPEN ↔ HALF-OPEN).
* Conditional GET via ETag (If-None-Match) and IMS (If-Modified-Since).
* Deterministic mapping to domain errors (402/429/400/401/403/422/5xx).
* Prometheus metrics + OpenTelemetry spans.

Return shapes:
* ``eod`` / ``intraday``: ``(payload, etag)``.
* ``eod_all`` / ``intraday_all``: ``(rows, meta)`` with optional ETag/Last-Modified.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from typing import Any, Final

import httpx

from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from stacklion_api.infrastructure.logging.logger import get_request_id, get_trace_id
from stacklion_api.infrastructure.observability.metrics_market_data import (
    get_market_data_errors_total,
    get_market_data_gateway_latency_seconds,
)
from stacklion_api.infrastructure.observability.tracing import traced
from stacklion_api.infrastructure.resilience.circuit_breaker import CircuitBreaker
from stacklion_api.infrastructure.resilience.retry import RetryPolicy, retry_async

# --------------------------------------------------------------------------- #
# Optional imports for additional metrics; safe fallbacks keep client working.
# --------------------------------------------------------------------------- #

try:
    from stacklion_api.infrastructure.observability.metrics_market_data import (
        get_market_data_304_total,
        get_market_data_breaker_events_total,
        get_market_data_http_status_total,
        get_market_data_response_bytes,
        get_market_data_retries_total,
    )

    _METRICS_FACTORY_HTTP_STATUS = get_market_data_http_status_total
    _METRICS_FACTORY_RESPONSE_BYTES = get_market_data_response_bytes
    _METRICS_FACTORY_RETRIES = get_market_data_retries_total
    _METRICS_FACTORY_304 = get_market_data_304_total
    _METRICS_FACTORY_BREAKER_EVENTS = get_market_data_breaker_events_total
except Exception:  # pragma: no cover

    class _NoopCounter:
        """Minimal Counter-like object used when Prometheus is unavailable."""

        def labels(self, *args: Any, **kwargs: Any) -> _NoopCounter:
            """Return self (no-op)."""
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            """Increment a counter (no-op)."""
            return None

    class _NoopHistogram:
        """Minimal Histogram-like object used when Prometheus is unavailable."""

        def labels(self, *args: Any, **kwargs: Any) -> _NoopHistogram:
            """Return self (no-op)."""
            return self

        def observe(self, *args: Any, **kwargs: Any) -> None:
            """Observe a value (no-op)."""
            return None

    def _METRICS_FACTORY_HTTP_STATUS() -> Any:
        """Return a no-op HTTP status counter."""
        return _NoopCounter()

    def _METRICS_FACTORY_RESPONSE_BYTES() -> Any:
        """Return a no-op response-bytes histogram."""
        return _NoopHistogram()

    def _METRICS_FACTORY_RETRIES() -> Any:
        """Return a no-op retries counter."""
        return _NoopCounter()

    def _METRICS_FACTORY_304() -> Any:
        """Return a no-op 304 counter."""
        return _NoopCounter()

    def _METRICS_FACTORY_BREAKER_EVENTS() -> Any:
        """Return a no-op breaker-events counter."""
        return _NoopCounter()


# --------------------------------------------------------------------------- #
# Defaults and headers
# --------------------------------------------------------------------------- #

_DEFAULT_TIMEOUT: Final[float] = 8.0
_DEFAULT_TOTAL_RETRIES: Final[int] = 4
_DEFAULT_BASE_BACKOFF: Final[float] = 0.25
_DEFAULT_MAX_BACKOFF: Final[float] = 2.5

_DEFAULT_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/json",
    "User-Agent": "stacklion-marketstack-client/1.0",
}


def _parse_retry_after(val: str | None) -> float | None:
    """Parse the HTTP ``Retry-After`` header (seconds form only).

    Args:
        val: Header value as a string, or ``None``.

    Returns:
        The seconds to wait as a float if parseable, otherwise ``None``.
    """
    if not val:
        return None
    try:
        return max(0.0, float(val))
    except Exception:
        return None


class MarketstackClient:
    """Resilient, instrumented transport client for Marketstack (V2)."""

    def __init__(
        self,
        settings: MarketstackSettings,
        *,
        http: httpx.AsyncClient | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        """Initialize the transport client.

        Args:
            settings: Provider settings loaded from environment or DI.
            http: Optional shared ``httpx.AsyncClient``. If omitted, a client
                is created and owned by this instance.
            timeout_s: Optional per-request timeout override in seconds.
                When omitted, ``settings.timeout_s`` is used. When both are
                unset, a safe default of ``8.0`` seconds is applied.
            retry_policy: Optional retry configuration for retryable failures.
                When omitted, a jittered exponential policy is built from
                ``settings.max_retries``.
            breaker: Circuit breaker instance to use; created if omitted.
        """
        self._settings = settings
        self._base_url = str(settings.base_url).rstrip("/")  # normalize AnyHttpUrl → str

        # Resolve effective timeout: explicit argument → settings.timeout_s → default.
        if timeout_s is not None:
            self._timeout = float(timeout_s)
        else:
            self._timeout = float(getattr(settings, "timeout_s", _DEFAULT_TIMEOUT))

        # Underlying HTTP client (either injected or owned).
        self._client = http or httpx.AsyncClient(
            timeout=self._timeout,
            headers=_DEFAULT_HEADERS.copy(),
        )
        if http is not None:
            # Ensure baseline headers exist on an injected client too,
            # without clobbering existing ones.
            for key, value in _DEFAULT_HEADERS.items():
                self._client.headers.setdefault(key, value)

        # Resolve retry policy: use provided policy or build from settings.
        total_retries = int(getattr(settings, "max_retries", _DEFAULT_TOTAL_RETRIES))
        self._retry = retry_policy or RetryPolicy(
            total=total_retries,
            base=_DEFAULT_BASE_BACKOFF,
            cap=_DEFAULT_MAX_BACKOFF,
            jitter=True,
        )

        # Circuit breaker: keep thresholds centralized here for now.
        self._breaker = breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout_s=30.0,
            half_open_max_calls=1,
        )

        # Metrics handles (real or no-op depending on import outcome).
        self._latency = get_market_data_gateway_latency_seconds()
        self._errors = get_market_data_errors_total()
        self._status_total = _METRICS_FACTORY_HTTP_STATUS()
        self._resp_bytes = _METRICS_FACTORY_RESPONSE_BYTES()
        self._retries_total = _METRICS_FACTORY_RETRIES()
        self._not_modified_total = _METRICS_FACTORY_304()
        self._breaker_events_total = _METRICS_FACTORY_BREAKER_EVENTS()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ---------------------------- Public API ----------------------------- #

    async def eod(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        page: int,
        limit: int,
        etag: str | None = None,
        if_modified_since: str | None = None,
    ) -> tuple[Mapping[str, Any], str | None]:
        """Call the V2 ``/eod`` endpoint and validate payload shape.

        Args:
            tickers: Sequence of symbols; normalized to uppercase.
            date_from: Inclusive ISO date (``YYYY-MM-DD``).
            date_to: Inclusive ISO date (``YYYY-MM-DD``).
            page: 1-based page index.
            limit: Page size.
            etag: Prior ETag for conditional GET (If-None-Match).
            if_modified_since: Prior Last-Modified for conditional GET.

        Returns:
            A tuple ``(payload, etag)`` where ``payload`` is the parsed JSON body.

        Raises:
            MarketDataValidationError: If the JSON does not contain a ``data`` list.
        """
        effective_limit = max(1, int(limit))
        params = {
            "symbols": ",".join(t.upper() for t in tickers),
            "access_key": self._settings.access_key.get_secret_value(),
            "date_from": date_from,
            "date_to": date_to,
            "limit": effective_limit,
            "offset": (page - 1) * effective_limit,
        }
        payload, etag_out, _last_mod = await self._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params=params,
            etag=etag,
            if_modified_since=if_modified_since,
        )

        # Shape check to satisfy tests: payload must contain a list under "data".
        data = payload.get("data")
        if not isinstance(data, list):
            raise MarketDataValidationError("bad_shape", details={"expected": "data:list"})

        return payload, etag_out

    async def intraday(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        interval: str,
        page: int,
        limit: int,
        etag: str | None = None,
        if_modified_since: str | None = None,
    ) -> tuple[Mapping[str, Any], str | None]:
        """Call the V2 ``/intraday`` endpoint.

        Args:
            tickers: Sequence of symbols; normalized to uppercase.
            date_from: Inclusive ISO timestamp (UTC) for window start.
            date_to: Exclusive ISO timestamp (UTC) for window end.
            interval: Provider interval label (e.g., ``"1min"``).
            page: 1-based page index.
            limit: Page size.
            etag: Prior ETag for conditional GET (If-None-Match).
            if_modified_since: Prior Last-Modified for conditional GET.

        Returns:
            A tuple ``(payload, etag)`` where ``payload`` is the parsed JSON body.
        """
        effective_limit = max(1, min(100, int(limit)))  # v2 intraday cap
        params = {
            "symbols": ",".join(t.upper() for t in tickers),
            "access_key": self._settings.access_key.get_secret_value(),
            "date_from": date_from,
            "date_to": date_to,
            "interval": interval,
            "limit": effective_limit,
            "offset": (page - 1) * effective_limit,
        }
        payload, etag_out, _last_mod = await self._observe_call(
            op="intraday",
            interval=interval,
            path="/intraday",
            params=params,
            etag=etag,
            if_modified_since=if_modified_since,
        )
        return payload, etag_out

    async def eod_all(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        page_size: int,
        max_pages: int | None = None,
        etag: str | None = None,
        if_modified_since: str | None = None,
    ) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
        """Fetch multiple pages from ``/eod`` and concatenate the ``data`` rows."""
        return await self._paged_all(
            endpoint="eod",
            interval="1d",
            build=lambda page: self._observe_call(
                op="eod",
                interval="1d",
                path="/eod",
                params={
                    "symbols": ",".join(t.upper() for t in tickers),
                    "access_key": self._settings.access_key.get_secret_value(),
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": page_size,
                    "offset": (page - 1) * page_size,
                },
                etag=etag if page == 1 else None,
                if_modified_since=if_modified_since if page == 1 else None,
            ),
            page_size=page_size,
            max_pages=max_pages,
        )

    async def intraday_all(
        self,
        *,
        tickers: Sequence[str],
        date_from: str,
        date_to: str,
        interval: str,
        page_size: int,
        max_pages: int | None = None,
        etag: str | None = None,
        if_modified_since: str | None = None,
    ) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
        """Fetch multiple pages from ``/intraday`` and concatenate the ``data`` rows."""
        return await self._paged_all(
            endpoint="intraday",
            interval=interval,
            build=lambda page: self._observe_call(
                op="intraday",
                interval=interval,
                path="/intraday",
                params={
                    "symbols": ",".join(t.upper() for t in tickers),
                    "access_key": self._settings.access_key.get_secret_value(),
                    "date_from": date_from,
                    "date_to": date_to,
                    "interval": interval,
                    "limit": page_size,
                    "offset": (page - 1) * page_size,
                },
                etag=etag if page == 1 else None,
                if_modified_since=if_modified_since if page == 1 else None,
            ),
            page_size=page_size,
            max_pages=max_pages,
        )

    # --------------------------- Internal helpers ------------------------- #

    async def _paged_all(
        self,
        *,
        endpoint: str,
        interval: str,
        build: Callable[[int], Awaitable[tuple[Mapping[str, Any], str | None, str | None]]],
        page_size: int,
        max_pages: int | None,
    ) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
        """Generic paginator that concatenates provider ``data`` rows."""
        rows: list[Mapping[str, Any]] = []
        etag_out: str | None = None
        last_mod_out: str | None = None

        page = 1
        while True:
            payload, etag, last_mod = await build(page)
            if etag:
                etag_out = etag
            if last_mod:
                last_mod_out = last_mod

            data = payload.get("data") if payload else None
            if not data:
                break
            if not isinstance(data, list):
                raise MarketDataValidationError("bad_shape", details={"expected": "data:list"})
            rows.extend(data)

            pagination = payload.get("pagination") if payload else None
            total = int(pagination.get("total", 0)) if isinstance(pagination, Mapping) else 0
            if total and len(rows) >= total:
                break

            page += 1
            if max_pages is not None and page > max_pages:
                break

        meta: dict[str, Any] = {}
        if etag_out:
            meta["etag"] = etag_out
        if last_mod_out:
            meta["last_modified"] = last_mod_out
        return rows, meta

    async def _observe_call(  # noqa: C901
        self,
        *,
        op: str,
        interval: str,
        path: str,
        params: Mapping[str, Any],
        etag: str | None,
        if_modified_since: str | None,
    ) -> tuple[Mapping[str, Any], str | None, str | None]:
        """Wrap a GET call with breaker, retry, metrics, and tracing."""
        provider = "marketstack"
        url = f"{self._base_url}{path}"

        headers: dict[str, str] = {}

        # Correlation propagation: carry request/trace ids on outbound calls.
        request_id = get_request_id()
        trace_id = get_trace_id()
        if request_id:
            headers.setdefault("X-Request-ID", request_id)
        if trace_id:
            headers.setdefault("x-trace-id", trace_id)

        if etag:
            headers["If-None-Match"] = etag
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since

        async def _call() -> tuple[Mapping[str, Any], str | None, str | None]:  # noqa: C901
            """Execute a single HTTP GET under breaker control."""
            # Circuit breaker guard (OPEN/HALF-OPEN failures are counted below).
            try:
                async with self._breaker.guard(provider):
                    response = await self._client.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=self._timeout,
                    )
            except RuntimeError as cb_exc:
                with suppress(Exception):
                    state = "open" if "open" in str(cb_exc).lower() else "half_open"
                    # provider, endpoint, state
                    self._breaker_events_total.labels(provider, op, state).inc()
                raise
            except httpx.RequestError as exc:
                # Treat transport/network errors (including timeouts) as provider
                # unavailability and let retry policy decide what to do.
                raise MarketDataUnavailable() from exc

            # Per-status metrics (best effort).
            with suppress(Exception):
                self._status_total.labels(provider, op, str(response.status_code)).inc()

            # Conditional GET path.
            if response.status_code == 304:
                with suppress(Exception):
                    self._not_modified_total.labels(provider, op).inc()
                return {}, response.headers.get("ETag"), response.headers.get("Last-Modified")

            # Pass-through provider errors for 400/401/403/422 with details.
            if response.status_code in (400, 401, 403, 422):
                details: dict[str, Any] = {"status": response.status_code}
                with suppress(Exception):
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("error"), dict):
                        err = body["error"]
                        details.update({"code": err.get("code"), "message": err.get("message")})
                raise MarketDataBadRequest(details=details)

            # Map to domain errors; honor Retry-After for retryable cases.
            try:
                self._map_errors(response.status_code)
            except (MarketDataRateLimited, MarketDataUnavailable) as exc:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if retry_after:
                    await asyncio.sleep(retry_after)
                raise exc

            # Observe response bytes (best effort).
            with suppress(Exception):
                length = response.headers.get("Content-Length")
                size = int(length) if length and length.isdigit() else len(response.content)
                self._resp_bytes.labels(provider, op).observe(float(size))

            # Parse JSON payload.
            try:
                payload: Mapping[str, Any] = response.json()
            except Exception as exc:  # noqa: BLE001
                raise MarketDataValidationError("non_json", details={"error": str(exc)}) from exc

            return payload, response.headers.get("ETag"), response.headers.get("Last-Modified")

        start = time.perf_counter()
        error_reason: str | None = None

        def _retry_predicate_with_metrics(
            exc_or_result: Exception | tuple[Mapping[str, Any], str | None, str | None],
        ) -> bool:
            """Return True for retryable conditions only.

            We *do not* retry generic exceptions or 4xx.
            """
            retryable = isinstance(
                exc_or_result,
                (
                    MarketDataRateLimited,  # 429
                    MarketDataUnavailable,  # transport/5xx
                    httpx.TimeoutException,  # explicit timeout class (defensive)
                    httpx.TransportError,  # network/transport
                ),
            )
            if retryable:
                with suppress(Exception):
                    self._retries_total.labels(provider, op, type(exc_or_result).__name__).inc()
            return retryable

        try:
            async with traced(
                f"{provider}.{op}", provider=provider, endpoint=op, interval=interval
            ):
                return await retry_async(
                    _call, policy=self._retry, retry_on=_retry_predicate_with_metrics
                )
        except (MarketDataRateLimited, MarketDataUnavailable) as exc:
            error_reason = type(exc).__name__
            raise
        except (MarketDataBadRequest, MarketDataQuotaExceeded, MarketDataValidationError) as exc:
            error_reason = type(exc).__name__
            raise
        finally:
            elapsed = time.perf_counter() - start
            # Best-effort metrics: histogram + error counter.
            with suppress(Exception):
                outcome = "error" if error_reason else "success"
                # Histogram: provider, endpoint, interval, outcome
                self._latency.labels(
                    provider=provider,
                    endpoint=op,
                    interval=interval,
                    outcome=outcome,
                ).observe(elapsed)

                if error_reason:
                    # Error counter: provider, endpoint, interval, reason
                    self._errors.labels(
                        provider=provider,
                        endpoint=op,
                        interval=interval,
                        reason=error_reason,
                    ).inc()

    @staticmethod
    def _map_errors(status: int) -> None:
        """Raise domain exceptions for retryable and terminal HTTP statuses."""
        if status == 429:
            raise MarketDataRateLimited()
        if status == 402:
            raise MarketDataQuotaExceeded()
        if status in (400, 422):
            raise MarketDataBadRequest()
        if status >= 500:
            raise MarketDataUnavailable()
