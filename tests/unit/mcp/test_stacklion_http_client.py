# tests/unit/mcp/test_stacklion_http_client.py
from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
import respx
from httpx import Response

from stacklion_api.mcp.client.stacklion_http import (
    StacklionHTTPClient,
    StacklionHTTPError,
)
from stacklion_api.mcp.schemas.errors import MCPError


@dataclass
class FakeSettings:
    """Minimal settings stub for HTTP client tests."""

    api_base_url: str = "https://api.stacklion.test"


@pytest.mark.anyio
@respx.mock
async def test_get_live_quotes_success() -> None:
    route = respx.get("https://api.stacklion.test/v2/quotes").mock(
        return_value=Response(
            status_code=200,
            json={"data": {"items": [{"ticker": "AAPL", "price": "1.23", "currency": "USD"}]}},
            headers={"X-Request-ID": "req-123"},
        )
    )

    client = StacklionHTTPClient(settings=FakeSettings())  # type: ignore[arg-type]
    resp = await client.get_live_quotes(["AAPL", "MSFT"])

    assert route.called
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] == "req-123"
    assert resp.body["data"]["items"][0]["ticker"] == "AAPL"


@pytest.mark.anyio
@respx.mock
async def test_get_live_quotes_non_json_response_raises() -> None:
    respx.get("https://api.stacklion.test/v2/quotes").mock(
        return_value=Response(
            status_code=200,
            content=b"not-json",
            headers={"Content-Type": "text/plain", "X-Request-ID": "req-456"},
        )
    )

    client = StacklionHTTPClient(settings=FakeSettings())  # type: ignore[arg-type]

    with pytest.raises(StacklionHTTPError) as excinfo:
        await client.get_live_quotes(["AAPL"])

    err = excinfo.value
    assert err.status_code == 200
    assert err.error_code == "NON_JSON_RESPONSE"
    assert err.trace_id == "req-456"


@pytest.mark.anyio
@respx.mock
async def test_http_error_maps_to_stacklion_http_error() -> None:
    respx.get("https://api.stacklion.test/v2/quotes").mock(
        return_value=Response(
            status_code=400,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "http_status": 400,
                    "message": "invalid input",
                    "details": {},
                    "trace_id": "trace-1",
                }
            },
            headers={"X-Request-ID": "req-789"},
        )
    )

    client = StacklionHTTPClient(settings=FakeSettings())  # type: ignore[arg-type]

    with pytest.raises(StacklionHTTPError) as excinfo:
        await client.get_live_quotes([""])

    err = excinfo.value
    assert err.status_code == 400
    assert err.error_code == "VALIDATION_ERROR"
    # Prefer error.trace_id over header
    assert err.trace_id == "trace-1"


@pytest.mark.anyio
@respx.mock
async def test_http_429_uses_retry_after_header() -> None:
    respx.get("https://api.stacklion.test/v2/quotes").mock(
        return_value=Response(
            status_code=429,
            json={
                "error": {
                    "code": "RATE_LIMITED",
                    "http_status": 429,
                    "message": "Too many requests",
                    "details": {},
                    "trace_id": "trace-429",
                }
            },
            headers={
                "X-Request-ID": "req-429",
                "Retry-After": "3",
            },
        )
    )

    client = StacklionHTTPClient(settings=FakeSettings())  # type: ignore[arg-type]

    with pytest.raises(StacklionHTTPError) as excinfo:
        await client.get_live_quotes(["AAPL"])

    err = excinfo.value
    assert err.status_code == 429
    assert err.error_code == "RATE_LIMITED"
    assert err.retry_after_s == 3.0


@pytest.mark.anyio
@respx.mock
async def test_network_error_maps_to_stacklion_http_error() -> None:
    url = "https://api.stacklion.test/v2/quotes"

    respx.get(url).mock(
        side_effect=httpx.ConnectError(
            message="boom",
            request=httpx.Request("GET", url),
        )
    )

    client = StacklionHTTPClient(settings=FakeSettings())  # type: ignore[arg-type]

    with pytest.raises(StacklionHTTPError) as excinfo:
        await client.get_live_quotes(["AAPL"])

    err = excinfo.value
    assert err.status_code is None
    assert err.error_code == "NETWORK_ERROR"
    assert err.retry_after_s is None


def test_to_mcp_error_non_retryable() -> None:
    exc = StacklionHTTPError(
        message="invalid",
        status_code=400,
        error_code="VALIDATION_ERROR",
        trace_id="trace-400",
        retry_after_s=None,
    )

    mcp_error = StacklionHTTPClient.to_mcp_error(exc)

    assert isinstance(mcp_error, MCPError)
    assert mcp_error.type == "VALIDATION_ERROR"
    assert mcp_error.retryable is False
    assert mcp_error.http_status == 400
    assert mcp_error.trace_id == "trace-400"
    assert mcp_error.retry_after_s is None


def test_to_mcp_error_retryable() -> None:
    exc = StacklionHTTPError(
        message="rate limited",
        status_code=429,
        error_code="RATE_LIMITED",
        trace_id="trace-429",
        retry_after_s=5.0,
    )

    mcp_error = StacklionHTTPClient.to_mcp_error(exc)

    assert mcp_error.retryable is True
    assert mcp_error.http_status == 429
    assert mcp_error.retry_after_s == 5.0
