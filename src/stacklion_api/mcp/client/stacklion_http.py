# src/stacklion_api/mcp/client/stacklion_http.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Stacklion HTTP Client for MCP.

Purpose:
- Thin async HTTP client that calls the existing Stacklion HTTP API surface:
    * GET /v2/quotes
    * GET /v2/quotes/historical
    * GET /healthz
- Maps HTTP/transport errors to a structured exception used by MCP capabilities.

Layer: adapters/mcp

Notes:
- No business logic; this client is transport-only.
- Uses Settings.api_base_url when provided, otherwise defaults to localhost.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.mcp.schemas.errors import MCPError


@dataclass(slots=True)
class StacklionHTTPError(Exception):
    """Structured error for HTTP/transport-level failures."""

    message: str
    status_code: int | None
    error_code: str | None
    trace_id: str | None
    retry_after_s: float | None

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class StacklionHTTPResponse:
    """Lightweight container for Stacklion HTTP responses."""

    status_code: int
    headers: Mapping[str, str]
    body: dict[str, Any]


class StacklionHTTPClient:
    """Async HTTP client to call the Stacklion API from MCP."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        base_url = self._settings.api_base_url
        # Fallback to a sensible local default for MCP deployments.
        self._base_url = str(base_url) if base_url is not None else "http://localhost:8000"
        self._timeout_s = 10.0

    async def _request(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> StacklionHTTPResponse:
        """Perform a GET request against the Stacklion API.

        Args:
            path: Path including version prefix, e.g. "/v2/quotes".
            params: Query parameters.

        Returns:
            Parsed StacklionHTTPResponse.

        Raises:
            StacklionHTTPError: On transport/HTTP-level failure.
        """
        request_id = uuid.uuid4().hex
        url = f"{self._base_url}{path}"

        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers={"X-Request-ID": request_id},
                )
            except httpx.RequestError as exc:
                raise StacklionHTTPError(
                    message=f"Network error calling Stacklion API: {exc}",
                    status_code=None,
                    error_code="NETWORK_ERROR",
                    trace_id=None,
                    retry_after_s=None,
                ) from exc

        # Normalize headers to lowercase keys for easier lookup
        headers: dict[str, str] = {k.lower(): v for k, v in resp.headers.items()}
        trace_id = headers.get("x-request-id")

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise StacklionHTTPError(
                message="Non-JSON response from Stacklion API.",
                status_code=resp.status_code,
                error_code="NON_JSON_RESPONSE",
                trace_id=trace_id,
                retry_after_s=_retry_after(headers),
            ) from exc

        if resp.status_code >= 400:
            error = body.get("error") if isinstance(body, dict) else None

            if isinstance(error, dict):
                raw_message = error.get("message")
                message = (
                    raw_message
                    if isinstance(raw_message, str)
                    else "HTTP error from Stacklion API."
                )
                error_code = error.get("code")
                error_trace_id = error.get("trace_id") or trace_id
            else:
                message = "HTTP error from Stacklion API."
                error_code = None
                error_trace_id = trace_id

            raise StacklionHTTPError(
                message=message,
                status_code=resp.status_code,
                error_code=error_code,
                trace_id=error_trace_id,
                retry_after_s=_retry_after(headers),
            )

        return StacklionHTTPResponse(
            status_code=resp.status_code,
            headers=headers,
            body=body if isinstance(body, dict) else {},
        )

    async def get_live_quotes(self, tickers: list[str]) -> StacklionHTTPResponse:
        """Call GET /v2/quotes with the given tickers."""
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
    ) -> StacklionHTTPResponse:
        """Call GET /v2/quotes/historical with the given parameters."""
        params: dict[str, Any] = {
            "tickers": tickers,
            "from_": from_,
            "to": to,
            "interval": interval,
            "page": page,
            "page_size": page_size,
        }
        return await self._request("/v2/quotes/historical", params=params)

    async def get_health(self) -> StacklionHTTPResponse:
        """Call GET /healthz."""
        return await self._request("/healthz")

    @staticmethod
    def to_mcp_error(exc: StacklionHTTPError) -> MCPError:
        """Convert a StacklionHTTPError to an MCPError."""
        status = exc.status_code
        code = exc.error_code or "INTERNAL_ERROR"

        # Retryability classification
        retryable = status in {429, 500, 502, 503, 504} or status is None

        return MCPError(
            type=code,
            message=exc.message,
            retryable=retryable,
            http_status=status,
            http_code=exc.error_code,
            trace_id=exc.trace_id,
            retry_after_s=exc.retry_after_s,
        )


def _retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse Retry-After header into seconds, if present."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
