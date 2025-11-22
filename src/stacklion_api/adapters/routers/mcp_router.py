# src/stacklion_api/adapters/routers/mcp_router.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
MCP HTTP Router (Adapters Layer)

Purpose:
    Expose the Stacklion MCP server over HTTP as a simple, typed endpoint:

        POST /mcp
            Body:  MCPRequest { "method": str, "params": { ... } | null }
            Reply: MCPResponse { "result": ..., "error": MCPError | null }

        GET /mcp/healthz
            Body:  -
            Reply: SystemHealthResult

This router is a thin adapter on top of the framework-agnostic MCP core in
`stacklion_api.mcp.server`. It does not contain business logic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stacklion_api.mcp.schemas.system import SystemHealthResult
from stacklion_api.mcp.server import MCPRequest, MCPResponse, MCPServer, UnknownMCPMethodError

router = APIRouter(prefix="/mcp", tags=["mcp"])

_mcp_server = MCPServer()


@router.post("", response_model=MCPResponse)
async def mcp_call(request: MCPRequest) -> MCPResponse:
    """HTTP entrypoint for MCP calls.

    Args:
        request: Validated MCPRequest parsed from the HTTP JSON body.

    Returns:
        MCPResponse object containing either a result or an error.

    Raises:
        HTTPException: If the MCP method is unknown or the MCP core raises an
            unexpected exception.
    """
    try:
        return await _mcp_server.call(request)
    except UnknownMCPMethodError as exc:
        # Map unknown method to HTTP 404. The MCP error schema can reflect this
        # further if needed at the capability layer.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Defensive catch-all to avoid leaking unstructured tracebacks to
        # external callers.
        raise HTTPException(
            status_code=500,
            detail=f"MCP server failure: {exc}",
        ) from exc


@router.get("/healthz", response_model=SystemHealthResult)
async def mcp_health() -> SystemHealthResult:
    """Health endpoint for the MCP server.

    Returns:
        SystemHealthResult describing the state of the MCP capabilities.
    """
    try:
        return await _mcp_server.health()
    except Exception:  # noqa: BLE001
        # If even the health check fails catastrophically, surface a degraded
        # synthetic result instead of breaking the route.
        return SystemHealthResult(
            status="degraded",
            request_id=None,
            source_status=500,
        )
