# tests/integration/mcp/test_mcp_server.py
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from arche_api.mcp import server as mcp_server
from arche_api.mcp.schemas.quotes_live import MCPQuote, QuotesLiveResult
from arche_api.mcp.schemas.system import SystemHealthResult, SystemMetadataResult


@pytest.mark.anyio
async def test_mcp_call_dispatches_quotes_live(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_quotes_live(params, settings):  # type: ignore[override]
        result = QuotesLiveResult(
            quotes=[
                MCPQuote(
                    ticker="AAPL",
                    price="192.34",
                    currency="USD",
                    as_of="2025-10-28T12:34:56Z",
                    volume=100,
                )
            ],
            request_id="req-mcp-live",
            source_status=200,
        )
        return result, None

    monkeypatch.setattr(mcp_server, "quotes_live", fake_quotes_live, raising=False)

    transport = ASGITransport(app=mcp_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/call",
            json={"method": "quotes.live", "params": {"tickers": ["AAPL"]}},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"] is None
    assert payload["result"]["quotes"][0]["ticker"] == "AAPL"
    assert payload["result"]["request_id"] == "req-mcp-live"


@pytest.mark.anyio
async def test_mcp_call_dispatches_system_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_system_metadata(settings):  # type: ignore[override]
        result = SystemMetadataResult(
            mcp_version="1.0.0",
            api_version="v2",
            quotes_contract_version="v1",
            supported_intervals=["1d", "1m"],
            max_page_size=200,
            max_range_days=365,
            max_tickers_per_request=50,
        )
        return result, None

    monkeypatch.setattr(mcp_server, "system_metadata", fake_system_metadata, raising=False)

    transport = ASGITransport(app=mcp_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/call",
            json={"method": "system.metadata", "params": {}},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"] is None
    result = payload["result"]
    assert result["mcp_version"] == "1.0.0"
    assert result["api_version"] == "v2"
    assert result["quotes_contract_version"] == "v1"


@pytest.mark.anyio
async def test_mcp_call_unknown_method_returns_404() -> None:
    transport = ASGITransport(app=mcp_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/call",
            json={"method": "unknown.method", "params": {}},
        )

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["detail"].startswith("Unknown MCP method")


@pytest.mark.anyio
async def test_mcp_health_uses_system_health(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_system_health(settings):  # type: ignore[override]
        result = SystemHealthResult(
            status="ok",
            request_id="req-mcp-health",
            source_status=200,
        )
        return result, None

    monkeypatch.setattr(mcp_server, "system_health", fake_system_health, raising=False)

    transport = ASGITransport(app=mcp_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["request_id"] == "req-mcp-health"
    assert payload["source_status"] == 200
