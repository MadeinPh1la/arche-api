# src/stacklion_api/mcp/capabilities/quotes_live.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Capability: quotes.live"""

from __future__ import annotations

from stacklion_api.config.settings import Settings
from stacklion_api.mcp.client.stacklion_http import (
    StacklionHTTPClient,
    StacklionHTTPError,
)
from stacklion_api.mcp.schemas.errors import MCPError
from stacklion_api.mcp.schemas.quotes_live import MCPQuote, QuotesLiveParams, QuotesLiveResult


async def quotes_live(
    params: QuotesLiveParams,
    settings: Settings,
) -> tuple[QuotesLiveResult | None, MCPError | None]:
    """Execute the `quotes.live` MCP method.

    Args:
        params: MCP input parameters.
        settings: Application settings.

    Returns:
        (result, error) where exactly one is non-None.
    """
    client = StacklionHTTPClient(settings=settings)

    try:
        resp = await client.get_live_quotes(params.tickers)
    except StacklionHTTPError as exc:
        return None, StacklionHTTPClient.to_mcp_error(exc)

    data = resp.body.get("data") or {}
    items = data.get("items") or []

    quotes: list[MCPQuote] = []
    for item in items:
        quotes.append(
            MCPQuote(
                ticker=item.get("ticker", ""),
                price=item.get("price", ""),
                currency=item.get("currency", ""),
                as_of=item.get("as_of"),
                volume=item.get("volume"),
            )
        )

    request_id = resp.headers.get("x-request-id")

    result = QuotesLiveResult(
        quotes=quotes,
        request_id=request_id,
        source_status=resp.status_code,
    )
    return result, None
