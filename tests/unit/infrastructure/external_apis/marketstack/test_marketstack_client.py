from __future__ import annotations

import httpx
import pytest
import respx

from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from arche_api.infrastructure.external_apis.marketstack.client import MarketstackClient
from arche_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from arche_api.infrastructure.logging.logger import set_request_context


@pytest.mark.asyncio
@respx.mock
async def test_eod_builds_params_and_returns_raw_plus_etag() -> None:
    cfg = MarketstackSettings(access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)
        expected = {
            "data": [
                {
                    "symbol": "AAPL",
                    "date": "2025-01-02T00:00:00Z",
                    "open": "1",
                    "high": "2",
                    "low": "0.5",
                    "close": "1.5",
                }
            ],
            "pagination": {"total": 1, "limit": 50, "offset": 0},
        }
        route = respx.get(f"{cfg.base_url}/eod").mock(
            return_value=httpx.Response(200, json=expected, headers={"ETag": 'W/"abc"'})
        )

        raw, etag = await client.eod(
            tickers=["AAPL"],
            date_from="2025-01-01",
            date_to="2025-01-02",
            page=1,
            limit=50,
        )
        assert route.called
        # verify params sent
        request = route.calls.last.request
        assert request.url.params["symbols"] == "AAPL"
        assert request.url.params["date_from"] == "2025-01-01"
        assert request.url.params["date_to"] == "2025-01-02"
        assert request.url.params["limit"] == "50"
        assert request.url.params["offset"] == "0"

        assert raw["pagination"]["total"] == 1
        assert raw["data"][0]["symbol"] == "AAPL"
        assert etag == 'W/"abc"'


@pytest.mark.asyncio
@respx.mock
async def test_intraday_maps_429_to_rate_limited() -> None:
    cfg = MarketstackSettings(access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)
        respx.get(f"{cfg.base_url}/intraday").mock(
            return_value=httpx.Response(429, json={"error": {}})
        )
        with pytest.raises(MarketDataRateLimited):
            await client.intraday(
                tickers=["AAPL"],
                date_from="2025-01-01T00:00:00Z",
                date_to="2025-01-02T00:00:00Z",
                interval="1m",
                page=1,
                limit=50,
            )


@pytest.mark.asyncio
@respx.mock
async def test_http_errors_mapped_and_json_shape_checked() -> None:
    cfg = MarketstackSettings(access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)

        # 402 -> Quota
        respx.get(f"{cfg.base_url}/eod").mock(return_value=httpx.Response(402, json={"error": {}}))
        with pytest.raises(MarketDataQuotaExceeded):
            await client.eod(
                tickers=["AAPL"], date_from="2025-01-01", date_to="2025-01-02", page=1, limit=1
            )

        # 400 -> BadRequest
        respx.get(f"{cfg.base_url}/eod").mock(return_value=httpx.Response(400, json={"error": {}}))
        with pytest.raises(MarketDataBadRequest):
            await client.eod(
                tickers=["AAPL"], date_from="2025-01-01", date_to="2025-01-02", page=1, limit=1
            )

        # 500 -> Unavailable
        respx.get(f"{cfg.base_url}/eod").mock(return_value=httpx.Response(500, json={"x": 1}))
        with pytest.raises(MarketDataUnavailable):
            await client.eod(
                tickers=["AAPL"], date_from="2025-01-01", date_to="2025-01-02", page=1, limit=1
            )

        # Non-JSON
        respx.get(f"{cfg.base_url}/eod").mock(
            return_value=httpx.Response(200, content=b"<html>not json</html>")
        )
        with pytest.raises(MarketDataValidationError):
            await client.eod(
                tickers=["AAPL"], date_from="2025-01-01", date_to="2025-01-02", page=1, limit=1
            )

        # Missing "data" key
        respx.get(f"{cfg.base_url}/eod").mock(
            return_value=httpx.Response(200, json={"unexpected": True})
        )
        with pytest.raises(MarketDataValidationError):
            await client.eod(
                tickers=["AAPL"], date_from="2025-01-01", date_to="2025-01-02", page=1, limit=1
            )


@pytest.mark.asyncio
@respx.mock
async def test_marketstack_client_propagates_request_and_trace_ids() -> None:
    """Client should propagate X-Request-ID and x-trace-id on outbound calls."""
    cfg = MarketstackSettings(access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)

        # Seed per-request context.
        set_request_context(request_id="req-123", trace_id="trace-abc")

        expected = {
            "data": [],
            "pagination": {"total": 0, "limit": 50, "offset": 0},
        }
        route = respx.get(f"{cfg.base_url}/eod").mock(
            return_value=httpx.Response(200, json=expected)
        )

        await client.eod(
            tickers=["AAPL"],
            date_from="2025-01-01",
            date_to="2025-01-02",
            page=1,
            limit=50,
        )

        assert route.called
        request = route.calls.last.request
        assert request.headers["X-Request-ID"] == "req-123"
        assert request.headers["x-trace-id"] == "trace-abc"

        # Reset context so other tests are not polluted.
        set_request_context(request_id=None, trace_id=None)
