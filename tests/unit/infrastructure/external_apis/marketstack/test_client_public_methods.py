from __future__ import annotations

from typing import Any

import pytest

from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackClient
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


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
        self.content = b"data"

    def json(self) -> Any:
        return self._body


class NoopMetric:
    def labels(self, *a: Any, **k: Any) -> NoopMetric:
        return self

    def observe(self, *a: Any, **k: Any) -> None:
        return None

    def inc(self, *a: Any, **k: Any) -> None:
        return None


def patch_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stacklion_api.infrastructure.observability.metrics_market_data.get_market_data_gateway_latency_seconds",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "stacklion_api.infrastructure.observability.metrics_market_data.get_market_data_errors_total",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_HTTP_STATUS",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_RESPONSE_BYTES",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_RETRIES",
        lambda: NoopMetric(),
    )
    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_304",
        lambda: NoopMetric(),
    )


def make_fake_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retry(func, policy, retry_on):
        return await func()

    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client.retry_async",
        fake_retry,
    )


class FakeBreaker:
    async def _ok_guard(self, _provider: str):
        yield

    def guard(self, provider: str):
        async def _cm():
            return
            yield  # pragma: no cover

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def ok(_p: str):
            yield

        return ok(provider)


# ---------------------------------------------------------------------------
# eod() tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_eod_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """eod() happy path: valid JSON with data list and ETag propagated."""
    patch_metrics(monkeypatch)
    make_fake_retry(monkeypatch)

    async def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {"data": [{"symbol": "AAPL"}]},
            headers={"ETag": "TAG1"},
        )

    class FakeClient:
        async def get(self, *a: Any, **k: Any) -> FakeResponse:
            return await fake_get(*a, **k)

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="https://x", access_key="y")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    payload, etag = await client.eod(
        tickers=["aapl"],
        date_from="2025-01-01",
        date_to="2025-01-02",
        page=1,
        limit=50,
    )

    assert payload["data"][0]["symbol"] == "AAPL"
    assert etag == "TAG1"


@pytest.mark.anyio
async def test_eod_bad_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """eod() must raise MarketDataValidationError if data missing or not list."""
    patch_metrics(monkeypatch)
    make_fake_retry(monkeypatch)

    async def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, {"wrong": []})

    class FakeClient:
        async def get(self, *a: Any, **k: Any) -> FakeResponse:
            return await fake_get(*a, **k)

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="https://x", access_key="y")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    with pytest.raises(MarketDataValidationError):
        await client.eod(
            tickers=["aapl"],
            date_from="2025-01-01",
            date_to="2025-01-02",
            page=1,
            limit=10,
        )


# ---------------------------------------------------------------------------
# intraday() tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_intraday_clamps_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """intraday() caps limit at 100."""
    patch_metrics(monkeypatch)
    make_fake_retry(monkeypatch)

    calls: dict[str, Any] = {}

    async def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        params = kwargs.get("params") or (args[1] if len(args) > 1 else {})
        calls["limit"] = params.get("limit")
        return FakeResponse(200, {"data": []}, headers={})

    class FakeClient:
        async def get(self, *a: Any, **k: Any) -> FakeResponse:
            return await fake_get(*a, **k)

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="https://x", access_key="y")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    await client.intraday(
        tickers=["aapl"],
        date_from="2025-01-01T00:00:00Z",
        date_to="2025-01-01T00:30:00Z",
        interval="1min",
        page=1,
        limit=500,  # Should clamp to 100
    )

    assert calls["limit"] == 100
