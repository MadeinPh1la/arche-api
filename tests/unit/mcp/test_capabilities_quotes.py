# tests/unit/mcp/test_capabilities_quotes.py
from __future__ import annotations

from dataclasses import dataclass

import pytest

from stacklion_api.mcp.capabilities import quotes_historical as quotes_historical_cap
from stacklion_api.mcp.capabilities import quotes_live as quotes_live_cap
from stacklion_api.mcp.client.stacklion_http import (
    StacklionHTTPClient,
    StacklionHTTPError,
    StacklionHTTPResponse,
)
from stacklion_api.mcp.schemas.errors import MCPError
from stacklion_api.mcp.schemas.quotes_historical import (
    MCPHistoricalBar,
    QuotesHistoricalParams,
    QuotesHistoricalResult,
)
from stacklion_api.mcp.schemas.quotes_live import MCPQuote, QuotesLiveParams, QuotesLiveResult


@dataclass
class FakeSettings:
    api_base_url: str = "https://api.stacklion.test"


@pytest.mark.anyio
async def test_quotes_live_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_live_quotes(
        self: StacklionHTTPClient, tickers: list[str]
    ) -> StacklionHTTPResponse:
        body = {
            "data": {
                "items": [
                    {
                        "ticker": "AAPL",
                        "price": "192.34",
                        "currency": "USD",
                        "as_of": "2025-10-28T12:34:56Z",
                        "volume": 100,
                    }
                ]
            }
        }
        return StacklionHTTPResponse(
            status_code=200,
            headers={"x-request-id": "req-live-1"},
            body=body,
        )

    monkeypatch.setattr(
        quotes_live_cap.StacklionHTTPClient,
        "get_live_quotes",
        _fake_get_live_quotes,
        raising=False,
    )

    params = QuotesLiveParams(tickers=["aapl", "MSFT"])
    result, error = await quotes_live_cap.quotes_live(params, settings=FakeSettings())  # type: ignore[arg-type]

    assert error is None
    assert result is not None
    assert isinstance(result, QuotesLiveResult)
    assert result.source_status == 200
    assert result.request_id == "req-live-1"
    assert len(result.quotes) == 1
    quote: MCPQuote = result.quotes[0]
    assert quote.ticker == "AAPL"
    assert quote.price == "192.34"
    assert quote.currency == "USD"
    assert quote.volume == 100


@pytest.mark.anyio
async def test_quotes_live_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_live_quotes_error(
        self: StacklionHTTPClient,
        tickers: list[str],
    ) -> StacklionHTTPResponse:
        raise StacklionHTTPError(
            message="Too many requests",
            status_code=429,
            error_code="RATE_LIMITED",
            trace_id="trace-live-429",
            retry_after_s=10.0,
        )

    monkeypatch.setattr(
        quotes_live_cap.StacklionHTTPClient,
        "get_live_quotes",
        _fake_get_live_quotes_error,
        raising=False,
    )

    params = QuotesLiveParams(tickers=["AAPL"])
    result, error = await quotes_live_cap.quotes_live(params, settings=FakeSettings())  # type: ignore[arg-type]

    assert result is None
    assert isinstance(error, MCPError)
    assert error.type == "RATE_LIMITED"
    assert error.retryable is True
    assert error.http_status == 429
    assert error.trace_id == "trace-live-429"
    assert error.retry_after_s == 10.0


@pytest.mark.anyio
async def test_quotes_historical_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_historical_quotes(
        self: StacklionHTTPClient,
        *,
        tickers: list[str],
        from_: str,
        to: str,
        interval: str,
        page: int,
        page_size: int,
    ) -> StacklionHTTPResponse:
        assert tickers == ["AAPL"]
        body = {
            "page": page,
            "page_size": page_size,
            "total": 1,
            "items": [
                {
                    "ticker": "AAPL",
                    "timestamp": "2025-01-02T00:00:00Z",
                    "open": "100.0",
                    "high": "110.0",
                    "low": "99.0",
                    "close": "105.0",
                    "volume": "123456",
                    "interval": "1d",
                }
            ],
        }
        return StacklionHTTPResponse(
            status_code=200,
            headers={"x-request-id": "req-hist-1"},
            body=body,
        )

    monkeypatch.setattr(
        quotes_historical_cap.StacklionHTTPClient,
        "get_historical_quotes",
        _fake_get_historical_quotes,
        raising=False,
    )

    params = QuotesHistoricalParams.model_validate(
        {
            "tickers": ["aapl"],
            "from": "2025-01-01",
            "to": "2025-01-31",
            "interval": "1d",
            "page": 1,
            "page_size": 50,
        }
    )

    result, error = await quotes_historical_cap.quotes_historical(
        params,
        settings=FakeSettings(),  # type: ignore[arg-type]
    )

    assert error is None
    assert result is not None
    assert isinstance(result, QuotesHistoricalResult)
    assert result.page == 1
    assert result.page_size == 50
    assert result.total == 1
    assert result.request_id == "req-hist-1"
    assert result.source_status == 200
    assert len(result.items) == 1
    bar: MCPHistoricalBar = result.items[0]
    assert bar.ticker == "AAPL"
    assert bar.interval == "1d"
    assert bar.open == "100.0"
    assert bar.volume == "123456"


@pytest.mark.anyio
async def test_quotes_historical_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_historical_quotes_error(
        self: StacklionHTTPClient,
        *,
        tickers: list[str],
        from_: str,
        to: str,
        interval: str,
        page: int,
        page_size: int,
    ) -> StacklionHTTPResponse:
        raise StacklionHTTPError(
            message="Market data unavailable",
            status_code=503,
            error_code="MARKET_DATA_UNAVAILABLE",
            trace_id="trace-hist-503",
            retry_after_s=None,
        )

    monkeypatch.setattr(
        quotes_historical_cap.StacklionHTTPClient,
        "get_historical_quotes",
        _fake_get_historical_quotes_error,
        raising=False,
    )

    params = QuotesHistoricalParams.model_validate(
        {
            "tickers": ["AAPL"],
            "from": "2025-01-01",
            "to": "2025-01-31",
            "interval": "1d",
            "page": 1,
            "page_size": 50,
        }
    )

    result, error = await quotes_historical_cap.quotes_historical(
        params,
        settings=FakeSettings(),  # type: ignore[arg-type]
    )

    assert result is None
    assert isinstance(error, MCPError)
    assert error.type == "MARKET_DATA_UNAVAILABLE"
    assert error.retryable is True
    assert error.http_status == 503
    assert error.trace_id == "trace-hist-503"
