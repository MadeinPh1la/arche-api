# src/stacklion_api/mcp/server.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Stacklion MCP Server.

Purpose:
    Thin HTTP surface implementing the Stacklion MCP methods over the
    existing Stacklion HTTP API. This server is intentionally small and
    does not contain business logic or ORM access.

Exposed MCP methods:
    - quotes.live
    - quotes.historical
    - system.health
    - system.metadata

Contract:
    - Input: MCPRequest { method: str, params: dict | null }
    - Output: MCPResponse { result: any | null, error: MCPError | null }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
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
    """Generic MCP request envelope."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(..., description="MCP method name (e.g. 'quotes.live').")
    params: dict[str, Any] | None = Field(
        default=None,
        description="Method-specific parameters object.",
    )


class MCPResponse(BaseModel):
    """Generic MCP response envelope."""

    model_config = ConfigDict(extra="forbid")

    result: Any | None = Field(
        default=None,
        description="Method-specific result payload on success.",
    )
    error: MCPError | None = Field(
        default=None,
        description="Error payload on failure.",
    )


app = FastAPI(
    title="Stacklion MCP Server",
    description="MCP surface on top of the Stacklion HTTP API.",
    version="1.0.0",
)


@app.post("/v1/call", response_model=MCPResponse)
async def mcp_call(request: MCPRequest) -> MCPResponse:
    """Single entrypoint for all MCP methods.

    Dispatches on `request.method` and validates the `params` payload
    into the appropriate MCP params model per method.
    """
    settings = get_settings()

    # quotes.live
    if request.method == "quotes.live":
        live_params = QuotesLiveParams.model_validate(request.params or {})
        live_result, live_error = await quotes_live(live_params, settings=settings)
        return MCPResponse(result=live_result, error=live_error)

    # quotes.historical
    if request.method == "quotes.historical":
        hist_params = QuotesHistoricalParams.model_validate(request.params or {})
        hist_result, hist_error = await quotes_historical(hist_params, settings=settings)
        return MCPResponse(result=hist_result, error=hist_error)

    # system.health
    if request.method == "system.health":
        health_result, health_error = await system_health(settings=settings)
        return MCPResponse(result=health_result, error=health_error)

    # system.metadata
    if request.method == "system.metadata":
        meta_result, meta_error = await system_metadata(settings=settings)
        return MCPResponse(result=meta_result, error=meta_error)

    # Unknown method: treat as 404 for the HTTP caller. Tests expect this.
    raise HTTPException(status_code=404, detail=f"Unknown MCP method: {request.method}")


@app.get("/healthz", response_model=SystemHealthResult)
async def mcp_health() -> SystemHealthResult:
    """Health endpoint for the MCP server itself.

    Delegates to `system.health` MCP capability and translates failures
    into a degraded SystemHealthResult instead of raising.
    """
    settings = get_settings()
    result, error = await system_health(settings=settings)

    if error is not None:
        return SystemHealthResult(
            status="degraded",
            request_id=error.trace_id,
            source_status=error.http_status or 500,
        )

    if result is None:
        raise HTTPException(
            status_code=500,
            detail="system_health returned neither result nor error",
        )

    return result
