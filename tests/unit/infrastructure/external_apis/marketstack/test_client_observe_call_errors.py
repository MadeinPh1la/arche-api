from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from arche_api.infrastructure.external_apis.marketstack.client import (
    MarketstackClient,
)
from arche_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = b"1234567890"

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class NoopMetric:
    def labels(self, *a: Any, **kw: Any) -> NoopMetric:
        return self

    def observe(self, *a: Any, **kw: Any) -> None:
        return None

    def inc(self, *a: Any, **kw: Any) -> None:
        return None


def patch_all_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_HTTP_STATUS",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_RESPONSE_BYTES",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_RETRIES",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_304",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_BREAKER_EVENTS",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.observability.metrics_market_data.get_market_data_errors_total",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "arche_api.infrastructure.observability.metrics_market_data.get_market_data_gateway_latency_seconds",
        lambda: NoopMetric(),
    )


def patch_retry_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retry(
        func: Callable[[], Awaitable[Any]],
        policy: Any,  # noqa: ARG001
        retry_on: Callable[[BaseException], bool],  # noqa: ARG001
    ) -> Any:
        return await func()

    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client.retry_async",
        fake_retry,
    )


def make_client(
    monkeypatch: pytest.MonkeyPatch,
    fake_get: Callable[[], Awaitable[FakeResponse]],
    breaker: Any | None = None,
) -> MarketstackClient:
    """Build a MarketstackClient with fake HTTP, without touching retry_async."""

    class FakeClient:
        async def get(self, *a: Any, **kw: Any) -> FakeResponse:  # noqa: ARG002
            return await fake_get()

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    @asynccontextmanager
    async def ok_guard(_provider: str):
        yield

    if breaker is None:

        class FakeBreaker:
            def guard(self, provider: str):
                return ok_guard(provider)

        breaker = FakeBreaker()

    settings = MarketstackSettings(base_url="https://x", access_key="Y")
    return MarketstackClient(settings, http=FakeClient(), breaker=breaker)


class RateLimitedFakeClient:
    """HTTP client that returns 429 once, then a 200 with an OK payload."""

    def __init__(self) -> None:
        self.calls = 0
        self.is_closed: bool = False
        self.headers: dict[str, str] = {}

    async def get(self, *a: Any, **kw: Any) -> FakeResponse:  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            # First call: 429 with Retry-After
            return FakeResponse(429, headers={"Retry-After": "1"})
        # Second call: success with payload + ETag
        return FakeResponse(200, body={"data": []}, headers={"ETag": "OK"})

    async def aclose(self) -> None:
        return None


@asynccontextmanager
async def _rate_limited_guard(_provider: str):
    """Circuit breaker guard that always allows the call."""
    yield


class RateLimitedBreaker:
    """Breaker that always yields a guard context (never opens)."""

    def guard(self, provider: str):
        return _rate_limited_guard(provider)


async def retry_twice(
    func: Callable[[], Awaitable[Any]],
    policy: Any,  # noqa: ARG001
    retry_on: Callable[[BaseException], bool],
) -> Any:
    """Custom retry: try once, then once more if retryable."""
    try:
        return await func()
    except Exception as exc:  # noqa: BLE001
        if retry_on(exc):
            return await func()
        raise


# ---------------------------------------------------------------------------
# Error branches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_observe_call_bad_request_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """400/401/403/422 with JSON error -> MarketDataBadRequest."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        return FakeResponse(
            400,
            {"error": {"code": "X", "message": "Bad"}},
            headers={},
        )

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataBadRequest) as info:
        await client._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params={},
            etag=None,
            if_modified_since=None,
        )

    details = info.value.details
    assert details["status"] == 400
    assert details["code"] == "X"
    assert details["message"] == "Bad"


@pytest.mark.anyio
async def test_observe_call_bad_request_non_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """400/401/403/422 non-JSON error body -> MarketDataBadRequest."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    class Boom(Exception):
        pass

    async def fake_get() -> FakeResponse:
        return FakeResponse(401, body=Boom("no json"))

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataBadRequest) as info:
        await client._observe_call(
            op="intraday",
            interval="1m",
            path="/intraday",
            params={},
            etag=None,
            if_modified_since=None,
        )

    assert info.value.details["status"] == 401


@pytest.mark.anyio
async def test_observe_call_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """402 -> MarketDataQuotaExceeded."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        return FakeResponse(402)

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataQuotaExceeded):
        await client._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params={},
            etag=None,
            if_modified_since=None,
        )


@pytest.mark.anyio
async def test_observe_call_rate_limited_without_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 without Retry-After -> MarketDataRateLimited."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        return FakeResponse(429)

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataRateLimited):
        await client._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params={},
            etag=None,
            if_modified_since=None,
        )


@pytest.mark.anyio
async def test_observe_call_rate_limited_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 WITH Retry-After and retry_async retries once (we don't assert timings)."""
    patch_all_metrics(monkeypatch)

    # Make sleep a no-op to avoid real delays.
    async def fake_sleep(_sec: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    settings = MarketstackSettings(base_url="https://x", access_key="Y")
    client = MarketstackClient(
        settings,
        http=RateLimitedFakeClient(),
        breaker=RateLimitedBreaker(),
    )

    # Patch retry_async to our custom "try twice" helper.
    monkeypatch.setattr(
        "arche_api.infrastructure.external_apis.marketstack.client.retry_async",
        retry_twice,
    )

    payload, etag, last_mod = await client._observe_call(
        op="eod",
        interval="1d",
        path="/eod",
        params={},
        etag=None,
        if_modified_since=None,
    )

    assert payload == {"data": []}
    assert etag == "OK"
    assert last_mod is None


@pytest.mark.anyio
async def test_observe_call_unavailable_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx -> MarketDataUnavailable."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        return FakeResponse(502)

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataUnavailable):
        await client._observe_call(
            op="intraday",
            interval="1m",
            path="/intraday",
            params={},
            etag=None,
            if_modified_since=None,
        )


@pytest.mark.anyio
async def test_observe_call_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx.RequestError -> MarketDataUnavailable."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        raise httpx.RequestError("boom")

    class FakeClient:
        async def get(self, *a: Any, **kw: Any) -> FakeResponse:  # noqa: ARG002
            return await fake_get()

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    @asynccontextmanager
    async def ok_guard(_provider: str):
        yield

    class FakeBreaker:
        def guard(self, provider: str):
            return ok_guard(provider)

    settings = MarketstackSettings(base_url="x", access_key="y")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    with pytest.raises(MarketDataUnavailable):
        await client._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params={},
            etag=None,
            if_modified_since=None,
        )


@pytest.mark.anyio
async def test_observe_call_json_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON parse failure -> MarketDataValidationError.

    Your implementation wraps JSON parse errors as a ValidationError with
    details['error']; we don't over-specify the internal code.
    """
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    class BadJSON(Exception):
        pass

    async def fake_get() -> FakeResponse:
        return FakeResponse(200, body=BadJSON("x"))

    client = make_client(monkeypatch, fake_get)

    with pytest.raises(MarketDataValidationError) as info:
        await client._observe_call(
            op="intraday",
            interval="1m",
            path="/intraday",
            params={},
            etag=None,
            if_modified_since=None,
        )

    assert "error" in info.value.details


@pytest.mark.anyio
async def test_observe_call_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Breaker OPEN -> RuntimeError surfaced, breaker error path executed."""
    patch_all_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get() -> FakeResponse:
        return FakeResponse(200, {"data": []})

    @asynccontextmanager
    async def fake_guard(_provider: str):
        # Simulate breaker that trips on enter.
        raise RuntimeError("circuit_open")
        yield  # pragma: no cover

    class FakeBreaker:
        def guard(self, provider: str):
            return fake_guard(provider)

    class FakeClient:
        async def get(self, *a: Any, **kw: Any) -> FakeResponse:  # noqa: ARG002
            return await fake_get()

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="x", access_key="y")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    with pytest.raises(RuntimeError):
        await client._observe_call(
            op="eod",
            interval="1d",
            path="/eod",
            params={},
            etag=None,
            if_modified_since=None,
        )
