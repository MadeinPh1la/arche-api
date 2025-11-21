# src/stacklion_api/mcp/capabilities/system_health.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Capability: system.health"""

from __future__ import annotations

from stacklion_api.config.settings import Settings
from stacklion_api.mcp.client.stacklion_http import (
    StacklionHTTPClient,
    StacklionHTTPError,
)
from stacklion_api.mcp.schemas.errors import MCPError
from stacklion_api.mcp.schemas.system import SystemHealthResult


async def system_health(
    settings: Settings,
) -> tuple[SystemHealthResult | None, MCPError | None]:
    """Execute the `system.health` MCP method.

    Args:
        settings: Application settings.

    Returns:
        (result, error) where exactly one is non-None.
    """
    client = StacklionHTTPClient(settings=settings)

    try:
        resp = await client.get_health()
    except StacklionHTTPError as exc:
        return None, StacklionHTTPClient.to_mcp_error(exc)

    body = resp.body
    status = body.get("status", "unknown")
    request_id = resp.headers.get("x-request-id")

    result = SystemHealthResult(
        status=status,
        request_id=request_id,
        source_status=resp.status_code,
    )
    return result, None
