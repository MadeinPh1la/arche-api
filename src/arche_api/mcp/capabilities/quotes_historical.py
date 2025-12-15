# src/arche_api/mcp/capabilities/quotes_historical.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""MCP Capability: quotes.historical"""

from __future__ import annotations

from arche_api.config.settings import Settings
from arche_api.mcp.client.arche_http import (
    ArcheHTTPClient,
    ArcheHTTPError,
)
from arche_api.mcp.schemas.errors import MCPError
from arche_api.mcp.schemas.quotes_historical import (
    MCPHistoricalBar,
    QuotesHistoricalParams,
    QuotesHistoricalResult,
)


async def quotes_historical(
    params: QuotesHistoricalParams,
    settings: Settings,
) -> tuple[QuotesHistoricalResult | None, MCPError | None]:
    """Execute the `quotes.historical` MCP method.

    Args:
        params: MCP input parameters.
        settings: Application settings.

    Returns:
        (result, error) where exactly one is non-None.
    """
    client = ArcheHTTPClient(settings=settings)

    try:
        resp = await client.get_historical_quotes(
            tickers=[t.strip().upper() for t in params.tickers if t.strip()],
            from_=params.from_.isoformat(),
            to=params.to.isoformat(),
            interval=params.interval,
            page=params.page,
            page_size=params.page_size,
        )
    except ArcheHTTPError as exc:
        return None, ArcheHTTPClient.to_mcp_error(exc)

    body = resp.body
    items = body.get("items") or []

    bars: list[MCPHistoricalBar] = []
    for item in items:
        bars.append(
            MCPHistoricalBar(
                ticker=item.get("ticker", ""),
                timestamp=item.get("timestamp"),
                open=str(item.get("open")),
                high=str(item.get("high")),
                low=str(item.get("low")),
                close=str(item.get("close")),
                volume=str(item["volume"]) if item.get("volume") is not None else None,
                interval=item.get("interval", params.interval),
            )
        )

    request_id = resp.headers.get("x-request-id")

    result = QuotesHistoricalResult(
        items=bars,
        page=body.get("page", params.page),
        page_size=body.get("page_size", params.page_size),
        total=body.get("total", len(bars)),
        request_id=request_id,
        source_status=resp.status_code,
    )
    return result, None
