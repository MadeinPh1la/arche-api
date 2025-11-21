# src/stacklion_api/mcp/capabilities/system_metadata.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Capability: system.metadata.

Purpose:
- Expose static metadata and usage limits for MCP clients.

Layer: adapters/mcp

Notes:
- This method does not hit the HTTP API; values are derived from the
  current MCP version and documented HTTP contract rules.
"""

from __future__ import annotations

from stacklion_api.config.settings import Settings
from stacklion_api.mcp.schemas.errors import MCPError
from stacklion_api.mcp.schemas.system import SystemMetadataResult


async def system_metadata(
    settings: Settings,
) -> tuple[SystemMetadataResult | None, MCPError | None]:
    """Execute the `system.metadata` MCP method.

    Args:
        settings: Application settings (used for api version metadata, if desired).

    Returns:
        Tuple of (result, error). Exactly one of result or error will be non-None.
    """
    # For now we treat API version as v2 (quotes endpoints under /v2/...).
    api_version = "v2"

    result = SystemMetadataResult(
        mcp_version="1.0.0",
        api_version=api_version,
        quotes_contract_version="v1",
        supported_intervals=["1d", "1m"],
        max_page_size=200,
        max_range_days=365,
        max_tickers_per_request=50,
    )
    return result, None
