# src/stacklion_api/mcp/server.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Stacklion MCP Server.

Purpose:
    Provide a small MCP dispatch layer that sits on top of the existing
    Stacklion configuration and capability functions. This module exposes:

    * A framework-agnostic MCPServer class for programmatic use.
    * A FastAPI `app` for HTTP-based integration tests and simple MCP-over-HTTP
      adapters.

Exposed MCP methods:
    - quotes.live
    - quotes.historical
    - system.health
    - system.metadata

Contract:
    - Input: MCPRequest { method: str, params: dict | null }
    - Output: MCPResponse { result: any | null, error: MCPError | null }

The HTTP adapter defined here is intentionally minimal. It:

    - Accepts MCPRequest envelopes as JSON.
    - Returns MCPResponse envelopes as JSON.
    - Uses HTTP 200 for successful calls and a simple HTTP 404 for unknown
      methods (to satisfy integration tests).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.config.settings import get_settings
from stacklion_api.mcp.capabilities.quotes_historical import quotes_historical
from stacklion_api.mcp.capabilities.quotes_live import quotes_live
from stacklion_api.mcp.capabilities.system_health import system_health
from stacklion_api.mcp.capabilities.system_metadata import system_metadata
from stacklion_api.mcp.schemas.errors import MCPError
from stacklion_api.mcp.schemas.quotes_historical import QuotesHistoricalParams
from stacklion_api.mcp.schemas.quotes_live import QuotesLiveParams
from stacklion_api.mcp.schemas.system import SystemHealthResult


class MCPRequest(BaseModel):
    """Generic MCP request envelope.

    Attributes:
        method: Fully-qualified MCP method name (e.g. ``"quotes.live"``).
        params: Optional method-specific parameters object.
    """

    model_config = ConfigDict(extra="forbid")

    method: str = Field(
        ...,
        description="MCP method name (e.g. 'quotes.live').",
    )
    params: Mapping[str, Any] | None = Field(
        default=None,
        description="Method-specific parameters object.",
    )


class MCPResponse(BaseModel):
    """Generic MCP response envelope.

    Attributes:
        result: Method-specific result payload on success.
        error: Structured error payload on failure.
    """

    model_config = ConfigDict(extra="forbid")

    result: Any | None = Field(
        default=None,
        description="Method-specific result payload on success.",
    )
    error: MCPError | None = Field(
        default=None,
        description="Error payload on failure.",
    )


class UnknownMCPMethodError(Exception):
    """Raised when an MCP method name is not recognized."""

    def __init__(self, method: str) -> None:
        """Initialize the unknown method error."""
        self.method = method
        super().__init__(f"Unknown MCP method: {method}")


class MCPServer:
    """Core MCP server for Stacklion.

    This class dispatches MCPRequest objects to the appropriate capability
    functions and returns MCPResponse envelopes. It is independent of HTTP
    transports; the FastAPI app below is a thin HTTP adapter.
    """

    async def call(self, request: MCPRequest) -> MCPResponse:
        """Dispatch a single MCP call.

        Args:
            request: Parsed MCPRequest instance.

        Returns:
            MCPResponse containing either `result` or `error`.

        Raises:
            UnknownMCPMethodError: If the requested method is not supported.
        """
        settings = get_settings()

        # quotes.live
        if request.method == "quotes.live":
            live_params = QuotesLiveParams.model_validate(request.params or {})
            live_result, live_error = await quotes_live(
                live_params,
                settings=settings,
            )
            return MCPResponse(result=live_result, error=live_error)

        # quotes.historical
        if request.method == "quotes.historical":
            hist_params = QuotesHistoricalParams.model_validate(request.params or {})
            hist_result, hist_error = await quotes_historical(
                hist_params,
                settings=settings,
            )
            return MCPResponse(result=hist_result, error=hist_error)

        # system.health
        if request.method == "system.health":
            health_result, health_error = await system_health(settings=settings)
            return MCPResponse(result=health_result, error=health_error)

        # system.metadata
        if request.method == "system.metadata":
            meta_result, meta_error = await system_metadata(settings=settings)
            return MCPResponse(result=meta_result, error=meta_error)

        # Unknown method: HTTP adapter will translate this into a 404.
        raise UnknownMCPMethodError(request.method)

    async def health(self) -> SystemHealthResult:
        """Return MCP server health information.

        This uses the `system.health` MCP capability and translates failures
        into a degraded SystemHealthResult instead of raising.

        Returns:
            A SystemHealthResult describing the MCP server health.

        Raises:
            RuntimeError: If the `system_health` capability returns neither
                result nor error.
        """
        settings = get_settings()
        result, error = await system_health(settings=settings)

        if error is not None:
            # Degraded but still answering; propagate trace and status.
            return SystemHealthResult(
                status="degraded",
                request_id=error.trace_id,
                source_status=error.http_status or 500,
            )

        if result is None:
            raise RuntimeError(
                "system_health returned neither result nor error",
            )

        return result


# --------------------------------------------------------------------------- #
# FastAPI HTTP adapter (used by integration tests and MCP-over-HTTP clients)
# --------------------------------------------------------------------------- #

mcp_server = MCPServer()

app = FastAPI(
    title="Stacklion MCP Server",
    version="0.0.1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.post(
    "/v1/call",
    response_model=MCPResponse,
    status_code=status.HTTP_200_OK,
    summary="Dispatch a generic MCP call.",
)
async def mcp_call_http(request: MCPRequest) -> MCPResponse:
    """HTTP entrypoint for generic MCP calls.

    This endpoint is transport glue: it accepts MCPRequest envelopes over HTTP
    and returns MCPResponse envelopes. Logical errors are encoded in the
    MCPResponse.error field; unknown methods are surfaced as HTTP 404.
    """
    try:
        return await mcp_server.call(request)
    except UnknownMCPMethodError as exc:
        # Tests expect a standard HTTP 404 with a human-readable detail string.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get(
    "/healthz",
    response_model=SystemHealthResult,
    status_code=status.HTTP_200_OK,
    summary="MCP health check.",
)
async def mcp_health_http() -> SystemHealthResult:
    """HTTP health endpoint for the MCP server."""
    return await mcp_server.health()
