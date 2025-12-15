# src/arche_api/infrastructure/external_apis/edgar/client.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR Transport Client — resilient, instrumented, async.

This transport is framework-agnostic and provides:

* Async HTTP (httpx) with per-request timeout.
* Jittered exponential retries (bounded).
* Circuit breaker (CLOSED ↔ OPEN ↔ HALF-OPEN).
* Deterministic mapping to EDGAR domain errors.
* OpenTelemetry spans and Prometheus-style metrics.

Endpoints:
    * fetch_company_submissions: submissions/CIK##########.json
    * fetch_recent_filings: currently an alias to submissions.
    * fetch_xbrl: best-effort XBRL instance document for a filing.

Notes:
    * We normalize CIKs to 10-digit, zero-padded strings.
    * Caller-facing exceptions are always EDGAR domain exceptions; httpx types
      are never allowed to cross the boundary.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Final

import httpx

from arche_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
    EdgarNotFound,
)
from arche_api.infrastructure.external_apis.edgar.settings import EdgarSettings
from arche_api.infrastructure.logging.logger import get_request_id, get_trace_id
from arche_api.infrastructure.observability.metrics_edgar import (
    get_edgar_304_total,
    get_edgar_breaker_events_total,
    get_edgar_errors_total,
    get_edgar_gateway_latency_seconds,
    get_edgar_http_status_total,
    get_edgar_response_bytes,
    get_edgar_retries_total,
)
from arche_api.infrastructure.observability.tracing import traced
from arche_api.infrastructure.resilience.circuit_breaker import CircuitBreaker
from arche_api.infrastructure.resilience.retry import RetryPolicy, retry_async

_DEFAULT_TIMEOUT: Final[float] = 8.0
_DEFAULT_TOTAL_RETRIES: Final[int] = 4
_DEFAULT_BASE_BACKOFF: Final[float] = 0.25
_DEFAULT_MAX_BACKOFF: Final[float] = 2.5

_DEFAULT_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/json",
    "User-Agent": "Arche/0.1 (+https://arche.io; support@arche.io)",
}


class EdgarClient:
    """Resilient, instrumented transport client for SEC EDGAR."""

    def __init__(
        self,
        settings: EdgarSettings,
        *,
        http: httpx.AsyncClient | None = None,
        timeout_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        """Initialize the transport client.

        Args:
            settings:
                Provider settings loaded from environment or DI.
            http:
                Optional shared ``httpx.AsyncClient``. If omitted, a client is
                created and owned by this instance.
            timeout_s:
                Optional per-request timeout override in seconds.
            retry_policy:
                Optional retry configuration for retryable failures.
            breaker:
                Circuit breaker instance to use; created if omitted.
        """
        self._settings = settings
        self._base_url = str(settings.base_url).rstrip("/")

        if timeout_s is not None:
            self._timeout = float(timeout_s)
        else:
            self._timeout = float(getattr(settings, "timeout_s", _DEFAULT_TIMEOUT))

        self._client = http or httpx.AsyncClient(
            timeout=self._timeout,
            headers=_DEFAULT_HEADERS.copy(),
        )
        if http is not None:
            for key, value in _DEFAULT_HEADERS.items():
                self._client.headers.setdefault(key, value)

        total_retries = int(getattr(settings, "max_retries", _DEFAULT_TOTAL_RETRIES))
        self._retry = retry_policy or RetryPolicy(
            total=total_retries,
            base=_DEFAULT_BASE_BACKOFF,
            cap=_DEFAULT_MAX_BACKOFF,
            jitter=True,
        )

        self._breaker = breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout_s=30.0,
            half_open_max_calls=1,
        )

        # Metrics handles.
        self._latency = get_edgar_gateway_latency_seconds()
        self._errors = get_edgar_errors_total()
        self._status_total = get_edgar_http_status_total()
        self._resp_bytes = get_edgar_response_bytes()
        self._retries_total = get_edgar_retries_total()
        self._not_modified_total = get_edgar_304_total()
        self._breaker_events_total = get_edgar_breaker_events_total()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def fetch_company_submissions(self, cik: str) -> Mapping[str, Any]:
        """Fetch the company submissions JSON document for a given CIK."""
        normalized_cik = self._normalize_cik(cik)
        path = f"/submissions/CIK{normalized_cik}.json"
        return await self._get_json(path, endpoint="company_submissions")

    async def fetch_recent_filings(self, cik: str) -> Mapping[str, Any]:
        """Fetch recent filings JSON for a given CIK.

        Currently this is an alias to ``fetch_company_submissions``; later
        phases may use EDGAR's dedicated "company facts" or recent filings
        endpoints as needed.
        """
        normalized_cik = self._normalize_cik(cik)
        path = f"/submissions/CIK{normalized_cik}.json"
        return await self._get_json(path, endpoint="recent_filings")

    async def fetch_xbrl(self, *, cik: str, accession_id: str) -> bytes:
        """Fetch primary XBRL instance bytes for a filing.

        This is a best-effort implementation using EDGAR's archive layout
        conventions. It is sufficient for E10-A and test environments; if the
        document cannot be retrieved, a clear :class:`EdgarIngestionError` is
        raised.

        Args:
            cik:
                Company CIK (may include non-digit characters; normalized
                internally).
            accession_id:
                EDGAR accession identifier (e.g., ``0000320193-24-000010``).

        Returns:
            Raw XBRL bytes for the primary instance document.

        Raises:
            EdgarIngestionError:
                If the document cannot be retrieved or a non-success status is
                returned.
        """
        normalized_cik = self._normalize_cik(cik)
        # EDGAR archives conventionally remove dashes in the accession number.
        acc_no_dashes = accession_id.replace("-", "")

        # Try common XBRL/inline-XBRL extensions in order.
        candidates = [
            f"/Archives/edgar/data/{int(normalized_cik)}/{acc_no_dashes}/{acc_no_dashes}.xml",
            f"/Archives/edgar/data/{int(normalized_cik)}/{acc_no_dashes}/{acc_no_dashes}.xbrl",
            f"/Archives/edgar/data/{int(normalized_cik)}/{acc_no_dashes}/{acc_no_dashes}.htm",
            f"/Archives/edgar/data/{int(normalized_cik)}/{acc_no_dashes}/{acc_no_dashes}_htm.xml",
        ]

        last_error: EdgarIngestionError | None = None
        for path in candidates:
            try:
                return await self._get_bytes(path, endpoint="xbrl_instance")
            except EdgarNotFound:
                # Try next candidate.
                continue
            except EdgarIngestionError as exc:
                last_error = exc
                break

        if last_error is not None:
            raise last_error

        raise EdgarIngestionError(
            "XBRL instance document not found in EDGAR archives.",
            details={"cik": cik, "accession_id": accession_id},
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_cik(cik: str) -> str:
        """Normalize a CIK string to a 10-digit, zero-padded value.

        Non-digit characters are stripped; remaining digits are left-padded
        with zeros up to 10 characters.

        Raises:
            EdgarMappingError: If no digits remain after normalization.
        """
        digits = "".join(ch for ch in cik if ch.isdigit())
        if not digits:
            raise EdgarMappingError(
                "CIK must contain at least one digit.",
                details={"cik": cik},
            )
        return digits.zfill(10)

    async def _get_json(self, path: str, *, endpoint: str) -> Mapping[str, Any]:
        """Perform a GET request and return a parsed JSON mapping.

        Args:
            path:
                Path relative to the EDGAR base URL.
            endpoint:
                Logical endpoint name for metrics (e.g., "company_submissions").

        Raises:
            EdgarNotFound:
                On 404 responses.
            EdgarIngestionError:
                On 4xx/5xx or transport failures.
            EdgarMappingError:
                On non-JSON or unexpected payloads.
        """
        provider = "edgar"
        url = f"{self._base_url}{path}"

        headers: dict[str, str] = {}
        request_id = get_request_id()
        trace_id = get_trace_id()
        if request_id:
            headers.setdefault("X-Request-ID", request_id)
        if trace_id:
            headers.setdefault("x-trace-id", trace_id)

        async def _call() -> Mapping[str, Any]:
            """Execute a single HTTP GET and map it into a JSON object."""
            response = await self._perform_request(
                url=url,
                headers=headers,
                provider=provider,
                endpoint=endpoint,
                path=path,
            )
            return self._handle_json_response(
                response=response,
                provider=provider,
                endpoint=endpoint,
                path=path,
            )

        def _retry_predicate(exc_or_result: Exception | Mapping[str, Any]) -> bool:
            """Return True for retryable conditions only."""
            if isinstance(exc_or_result, EdgarIngestionError):
                with suppress(Exception):
                    self._retries_total.labels(
                        provider, endpoint, type(exc_or_result).__name__
                    ).inc()
                return True

            if isinstance(
                exc_or_result,
                (httpx.TimeoutException, httpx.TransportError),
            ):
                with suppress(Exception):
                    self._retries_total.labels(
                        provider, endpoint, type(exc_or_result).__name__
                    ).inc()
                return True

            return False

        start = time.perf_counter()
        error_reason: str | None = None

        try:
            async with traced("edgar.http", provider=provider, endpoint=endpoint, path=path):
                return await retry_async(_call, policy=self._retry, retry_on=_retry_predicate)
        except (EdgarNotFound, EdgarIngestionError, EdgarMappingError) as exc:
            error_reason = type(exc).__name__
            raise
        finally:
            elapsed = time.perf_counter() - start
            outcome = "error" if error_reason else "success"
            with suppress(Exception):
                self._latency.labels(
                    provider=provider,
                    endpoint=endpoint,
                    outcome=outcome,
                ).observe(elapsed)
                if error_reason:
                    self._errors.labels(
                        provider=provider,
                        endpoint=endpoint,
                        reason=error_reason,
                    ).inc()

    async def _get_bytes(self, path: str, *, endpoint: str) -> bytes:
        """Perform a GET request and return raw bytes.

        Args:
            path:
                Path relative to the EDGAR base URL.
            endpoint:
                Logical endpoint name for metrics (e.g., "xbrl_instance").

        Raises:
            EdgarNotFound:
                On 404 responses.
            EdgarIngestionError:
                On 4xx/5xx or transport failures.
        """
        provider = "edgar"
        url = f"{self._base_url}{path}"

        headers: dict[str, str] = {}
        request_id = get_request_id()
        trace_id = get_trace_id()
        if request_id:
            headers.setdefault("X-Request-ID", request_id)
        if trace_id:
            headers.setdefault("x-trace-id", trace_id)

        async def _call() -> bytes:
            """Execute a single HTTP GET and return raw bytes."""
            response = await self._perform_request(
                url=url,
                headers=headers,
                provider=provider,
                endpoint=endpoint,
                path=path,
            )
            return self._handle_bytes_response(
                response=response,
                provider=provider,
                endpoint=endpoint,
                path=path,
            )

        def _retry_predicate(exc_or_result: Exception | bytes) -> bool:
            """Return True for retryable conditions only."""
            if isinstance(exc_or_result, EdgarIngestionError):
                with suppress(Exception):
                    self._retries_total.labels(
                        provider, endpoint, type(exc_or_result).__name__
                    ).inc()
                return True

            if isinstance(
                exc_or_result,
                (httpx.TimeoutException, httpx.TransportError),
            ):
                with suppress(Exception):
                    self._retries_total.labels(
                        provider, endpoint, type(exc_or_result).__name__
                    ).inc()
                return True

            return False

        start = time.perf_counter()
        error_reason: str | None = None

        try:
            async with traced("edgar.http", provider=provider, endpoint=endpoint, path=path):
                return await retry_async(_call, policy=self._retry, retry_on=_retry_predicate)
        except (EdgarNotFound, EdgarIngestionError) as exc:
            error_reason = type(exc).__name__
            raise
        finally:
            elapsed = time.perf_counter() - start
            outcome = "error" if error_reason else "success"
            with suppress(Exception):
                self._latency.labels(
                    provider=provider,
                    endpoint=endpoint,
                    outcome=outcome,
                ).observe(elapsed)
                if error_reason:
                    self._errors.labels(
                        provider=provider,
                        endpoint=endpoint,
                        reason=error_reason,
                    ).inc()

    async def _perform_request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        provider: str,
        endpoint: str,
        path: str,
    ) -> httpx.Response:
        """Execute a single HTTP GET under breaker control and map transport errors."""
        try:
            async with self._breaker.guard(provider):
                return await self._client.get(
                    url,
                    headers=headers,
                    timeout=self._timeout,
                )
        except RuntimeError as cb_exc:
            with suppress(Exception):
                state = "open" if "open" in str(cb_exc).lower() else "half_open"
                self._breaker_events_total.labels(provider, endpoint, state).inc()
            raise EdgarIngestionError(
                "EDGAR circuit breaker is open.",
                details={"endpoint": endpoint, "path": path},
            ) from cb_exc
        except httpx.RequestError as exc:
            raise EdgarIngestionError(
                "EDGAR transport failure.",
                details={"endpoint": endpoint, "path": path, "error": str(exc)},
            ) from exc

    def _handle_json_response(  # noqa: C901
        self,
        *,
        response: httpx.Response,
        provider: str,
        endpoint: str,
        path: str,
    ) -> Mapping[str, Any]:
        """Map an HTTP response into a JSON object or domain error."""
        # Status metrics.
        with suppress(Exception):
            self._status_total.labels(provider, endpoint, str(response.status_code)).inc()

        # EDGAR doesn't really use 304 here, but it costs nothing to handle.
        if response.status_code == 304:
            with suppress(Exception):
                self._not_modified_total.labels(provider, endpoint).inc()
            return {}

        if response.status_code == 404:
            raise EdgarNotFound(
                "EDGAR resource not found.",
                details={"endpoint": endpoint, "path": path, "status": 404},
            )

        if response.status_code == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                # Honor upstream back-off hint, but still surface error.
                asyncio.run(asyncio.sleep(retry_after))  # pragma: no cover
            raise EdgarIngestionError(
                "EDGAR rate limited.",
                details={
                    "endpoint": endpoint,
                    "path": path,
                    "status": 429,
                    "retry_after_s": retry_after,
                },
            )

        if 400 <= response.status_code < 500:
            raise EdgarIngestionError(
                "EDGAR bad request.",
                details={"endpoint": endpoint, "path": path, "status": response.status_code},
            )

        if response.status_code >= 500:
            raise EdgarIngestionError(
                "EDGAR upstream unavailable.",
                details={"endpoint": endpoint, "path": path, "status": response.status_code},
            )

        # Response size metrics.
        with suppress(Exception):
            length = response.headers.get("Content-Length")
            size = int(length) if length and length.isdigit() else len(response.content)
            self._resp_bytes.labels(provider, endpoint).observe(float(size))

        try:
            payload: Any = response.json()
        except Exception as exc:  # noqa: BLE001
            raise EdgarMappingError(
                "EDGAR response was not valid JSON.",
                details={"endpoint": endpoint, "path": path, "error": str(exc)},
            ) from exc

        if not isinstance(payload, Mapping):
            raise EdgarMappingError(
                "EDGAR JSON response must be an object.",
                details={"endpoint": endpoint, "path": path, "type": type(payload).__name__},
            )

        return payload

    def _handle_bytes_response(
        self,
        *,
        response: httpx.Response,
        provider: str,
        endpoint: str,
        path: str,
    ) -> bytes:
        """Map an HTTP response into raw bytes or domain error."""
        with suppress(Exception):
            self._status_total.labels(provider, endpoint, str(response.status_code)).inc()

        if response.status_code == 304:
            with suppress(Exception):
                self._not_modified_total.labels(provider, endpoint).inc()
            return b""

        if response.status_code == 404:
            raise EdgarNotFound(
                "EDGAR resource not found.",
                details={"endpoint": endpoint, "path": path, "status": 404},
            )

        if response.status_code == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                asyncio.run(asyncio.sleep(retry_after))  # pragma: no cover
            raise EdgarIngestionError(
                "EDGAR rate limited.",
                details={
                    "endpoint": endpoint,
                    "path": path,
                    "status": 429,
                    "retry_after_s": retry_after,
                },
            )

        if 400 <= response.status_code < 500:
            raise EdgarIngestionError(
                "EDGAR bad request.",
                details={"endpoint": endpoint, "path": path, "status": response.status_code},
            )

        if response.status_code >= 500:
            raise EdgarIngestionError(
                "EDGAR upstream unavailable.",
                details={"endpoint": endpoint, "path": path, "status": response.status_code},
            )

        with suppress(Exception):
            length = response.headers.get("Content-Length")
            size = int(length) if length and length.isdigit() else len(response.content)
            self._resp_bytes.labels(provider, endpoint).observe(float(size))

        return response.content

    @staticmethod
    def _parse_retry_after(val: str | None) -> float | None:
        """Parse HTTP Retry-After header (seconds form only)."""
        if not val:
            return None
        try:
            seconds = float(val)
        except (TypeError, ValueError):
            return None
        return max(0.0, seconds)
