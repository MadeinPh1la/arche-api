# src/arche_api/mcp/client/arche_http.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Arche HTTP Client for MCP.

Purpose:
    Thin async HTTP client that calls the existing Arche HTTP API surface:

        * GET /v2/quotes
        * GET /v2/quotes/historical
        * GET /healthz

    This client is transport-only and is responsible for:

        * Building the full request URL against the configured base URL.
        * Attaching authentication headers for MCP→HTTP calls (when using real Settings).
        * Propagating request IDs for observability.
        * Mapping HTTP/transport errors into MCPError instances for MCP capabilities.

Layer:
    adapters/mcp

Notes:
    - Base URL precedence when a real Settings instance is provided:

        1. Settings.mcp_http_base_url
        2. Settings.api_base_url
        3. "http://127.0.0.1:8000"

    - When a lightweight settings object (e.g., tests' FakeSettings) is passed,
      only `api_base_url` is read; MCP-specific fields are ignored.

    - Auth precedence (when using real Settings):

        1. mcp_http_bearer_token → Authorization: Bearer <token>
        2. mcp_http_api_key → X-Api-Key: <key>
        3. api_key (legacy dev-only) → X-Api-Key: <key>

    - Error mapping:

        * 401 → MCP type "UNAUTHENTICATED"
        * 403 → MCP type "FORBIDDEN"
        * 429 → MCP type "RATE_LIMITED"
        * Other 4xx/5xx → MCP type derived from HTTP error code or "INTERNAL_ERROR"
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from arche_api.config.settings import Settings, get_settings
from arche_api.mcp.schemas.errors import MCPError


@dataclass(slots=True)
class ArcheHTTPError(Exception):
    """Structured error for HTTP/transport-level failures.

    Attributes:
        message: Human-readable error message.
        status_code: HTTP status code if available, otherwise None for transport errors.
        error_code: Arche HTTP error code from the ErrorEnvelope, if present.
        trace_id: Trace or request ID associated with the failing request, if known.
        retry_after_s: Parsed Retry-After header value in seconds, if present.
    """

    message: str
    status_code: int | None
    error_code: str | None
    trace_id: str | None
    retry_after_s: float | None

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class ArcheHTTPResponse:
    """Lightweight container for Arche HTTP responses.

    Attributes:
        status_code: HTTP status code for the response.
        headers: Normalized response headers (lowercased keys).
        body: Parsed JSON body as a dictionary. Non-dict responses are coerced to `{}`.
    """

    status_code: int
    headers: Mapping[str, str]
    body: dict[str, Any]


class ArcheHTTPClient:
    """Async HTTP client to call the Arche API from MCP.

    The client is configured from application Settings and is safe to reuse
    across MCP capabilities. It is intentionally minimal and does not contain
    business logic.
    """

    def __init__(self, settings: Settings | Any | None = None) -> None:
        """Initialize the HTTP client.

        Args:
            settings:
                Optional settings object. When a real `Settings` instance is
                provided, MCP-specific configuration (mcp_http_base_url,
                mcp_http_api_key, mcp_http_bearer_token, api_key) is honored.
                When a lightweight object (such as tests' FakeSettings) is
                provided, only `api_base_url` is read and MCP-specific fields
                are ignored.
        """
        self._settings: Any = settings or get_settings()

        # Base URL precedence when using real Settings:
        #   1. mcp_http_base_url
        #   2. api_base_url
        #   3. "http://127.0.0.1:8000"
        #
        # When using a lightweight FakeSettings (tests), only api_base_url is
        # used and MCP-specific attributes are skipped to avoid AttributeError.
        if isinstance(self._settings, Settings):
            if self._settings.mcp_http_base_url is not None:
                base_url = str(self._settings.mcp_http_base_url)
            elif self._settings.api_base_url is not None:
                base_url = str(self._settings.api_base_url)
            else:
                base_url = "http://127.0.0.1:8000"
        else:
            base_url = getattr(self._settings, "api_base_url", None) or "http://127.0.0.1:8000"

        # Normalize and strip trailing slash for path concatenation.
        self._base_url = base_url.rstrip("/")

        # Conservative default timeout; can be tuned via dedicated MCP settings in the future.
        self._timeout_s = 10.0

    async def _request(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> ArcheHTTPResponse:
        """Perform a GET request against the Arche API.

        Args:
            path: Path including version prefix, for example "/v2/quotes".
            params: Query parameters to append to the request.

        Returns:
            Parsed ArcheHTTPResponse with status, headers, and JSON body.

        Raises:
            ArcheHTTPError: On transport failure or non-successful HTTP status.
        """
        request_id = uuid.uuid4().hex
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self._base_url}{normalized_path}"
        headers = self._build_headers(request_id=request_id)

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                raise ArcheHTTPError(
                    message=f"Network error calling Arche API: {exc}",
                    status_code=None,
                    error_code="NETWORK_ERROR",
                    trace_id=None,
                    retry_after_s=None,
                ) from exc

        # Normalize headers to lowercase keys for easier lookup.
        normalized_headers: dict[str, str] = {k.lower(): v for k, v in resp.headers.items()}
        trace_id = normalized_headers.get("x-request-id")

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ArcheHTTPError(
                message="Non-JSON response from Arche API.",
                status_code=resp.status_code,
                error_code="NON_JSON_RESPONSE",
                trace_id=trace_id,
                retry_after_s=_retry_after(normalized_headers),
            ) from exc

        if resp.status_code >= 400:
            error_payload = body.get("error") if isinstance(body, dict) else None

            if isinstance(error_payload, dict):
                raw_message = error_payload.get("message")
                message = (
                    raw_message if isinstance(raw_message, str) else "HTTP error from Arche API."
                )
                error_code = error_payload.get("code")
                error_trace_id = error_payload.get("trace_id") or trace_id
            else:
                message = "HTTP error from Arche API."
                error_code = None
                error_trace_id = trace_id

            raise ArcheHTTPError(
                message=message,
                status_code=resp.status_code,
                error_code=error_code,
                trace_id=error_trace_id,
                retry_after_s=_retry_after(normalized_headers),
            )

        return ArcheHTTPResponse(
            status_code=resp.status_code,
            headers=normalized_headers,
            body=body if isinstance(body, dict) else {},
        )

    def _build_headers(self, request_id: str) -> dict[str, str]:
        """Build HTTP headers for MCP→HTTP API calls.

        When a real Settings instance is in use, authentication headers are
        attached according to the following precedence:

            1. mcp_http_bearer_token → Authorization: Bearer <token>
            2. mcp_http_api_key → X-Api-Key: <key>
            3. api_key (legacy dev-only) → X-Api-Key: <key>

        For lightweight settings objects (e.g. tests' FakeSettings), only
        basic headers (X-Request-ID, Accept) are set and no auth headers are
        attached to avoid relying on attributes that are not present.

        Args:
            request_id: Unique request identifier for observability and tracing.

        Returns:
            Dictionary of headers to attach to the outgoing HTTP request.
        """
        headers: dict[str, str] = {
            "X-Request-ID": request_id,
            "Accept": "application/json",
        }

        # Only perform auth header logic when using the real Settings schema.
        if not isinstance(self._settings, Settings):
            return headers

        # Bearer token takes precedence when configured.
        if self._settings.mcp_http_bearer_token is not None:
            token = self._settings.mcp_http_bearer_token.get_secret_value().strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                return headers

        # MCP-specific API key if present.
        if self._settings.mcp_http_api_key is not None:
            api_key = self._settings.mcp_http_api_key.get_secret_value().strip()
            if api_key:
                headers["X-Api-Key"] = api_key
                return headers

        # Legacy dev-only API key as a final fallback.
        if self._settings.api_key:
            legacy_key = self._settings.api_key.strip()
            if legacy_key:
                headers["X-Api-Key"] = legacy_key

        return headers

    async def get_live_quotes(self, tickers: list[str]) -> ArcheHTTPResponse:
        """Call GET /v2/quotes with the given tickers.

        Args:
            tickers: List of ticker symbols. Symbols are uppercased and de-duplicated.

        Returns:
            ArcheHTTPResponse containing the quote payload on success.

        Raises:
            ArcheHTTPError: If the HTTP request fails or returns an error status.
        """
        tickers_csv = ",".join(sorted({t.strip().upper() for t in tickers if t.strip()}))
        return await self._request("/v2/quotes", params={"tickers": tickers_csv})

    async def get_historical_quotes(
        self,
        *,
        tickers: list[str],
        from_: str,
        to: str,
        interval: str,
        page: int,
        page_size: int,
    ) -> ArcheHTTPResponse:
        """Call GET /v2/quotes/historical with the given parameters.

        Args:
            tickers: List of ticker symbols to query historical bars for.
            from_: Start timestamp (inclusive) in ISO-8601 string form.
            to: End timestamp (exclusive) in ISO-8601 string form.
            interval: Bar interval label (for example, '1d', '1min').
            page: Page number for paginated historical responses.
            page_size: Number of items per page.

        Returns:
            ArcheHTTPResponse containing the historical quote payload.

        Raises:
            ArcheHTTPError: If the HTTP request fails or returns an error status.
        """
        params: dict[str, Any] = {
            "tickers": tickers,
            "from_": from_,
            "to": to,
            "interval": interval,
            "page": page,
            "page_size": page_size,
        }
        return await self._request("/v2/quotes/historical", params=params)

    async def get_health(self) -> ArcheHTTPResponse:
        """Call GET /healthz.

        Returns:
            ArcheHTTPResponse representing the health payload.

        Raises:
            ArcheHTTPError: If the HTTP request fails or returns an error status.
        """
        return await self._request("/healthz")

    @staticmethod
    def to_mcp_error(exc: ArcheHTTPError) -> MCPError:
        """Convert a ArcheHTTPError to an MCPError.

        This adapter enforces consistent MCP error semantics for auth and rate
        limiting:

            * 401 → type="UNAUTHENTICATED"
            * 403 → type="FORBIDDEN"
            * 429 → type="RATE_LIMITED"
            * Other → type from error_code, or "INTERNAL_ERROR" as a fallback.

        Retries are suggested for:

            * Network/transport failures (status_code is None)
            * 429, 500, 502, 503, 504
        """
        status = exc.status_code

        # Map HTTP status codes to stable MCP error types.
        if status == 401:
            mcp_type = "UNAUTHENTICATED"
        elif status == 403:
            mcp_type = "FORBIDDEN"
        elif status == 429:
            mcp_type = "RATE_LIMITED"
        else:
            mcp_type = exc.error_code or "INTERNAL_ERROR"

        # Retryability classification.
        retryable = status in {429, 500, 502, 503, 504} or status is None

        return MCPError(
            type=mcp_type,
            message=exc.message,
            retryable=retryable,
            http_status=status,
            http_code=exc.error_code,
            trace_id=exc.trace_id,
            retry_after_s=exc.retry_after_s,
        )


def _retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse the Retry-After header into seconds, if present.

    Args:
        headers: Normalized HTTP headers with lowercase keys.

    Returns:
        Parsed Retry-After value as a float number of seconds, or None if the
        header is absent or cannot be parsed.
    """
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
