from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from stacklion_api.infrastructure.external_apis.marketstack.client import (
    MarketstackClient,
)
from stacklion_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)


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
        self.content = b"123456"

    def json(self) -> Any:
        return self._body


class NoopMetric:
    def labels(self, *a: Any, **kw: Any) -> NoopMetric:
        return self

    def observe(self, *a: Any, **kw: Any) -> None:
        return None

    def inc(self, *a: Any, **kw: Any) -> None:
        return None


def patch_minimal_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client._METRICS_FACTORY_BREAKER_EVENTS",
        lambda: NoopMetric(),
    )


def patch_retry_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retry(func, policy, retry_on):
        return await func()

    monkeypatch.setattr(
        "stacklion_api.infrastructure.external_apis.marketstack.client.retry_async",
        fake_retry,
    )


@asynccontextmanager
async def ok_guard(_provider: str):
    yield


class FakeBreaker:
    def guard(self, provider: str):
        return ok_guard(provider)


@pytest.mark.anyio
async def test_observe_call_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Basic 200 success path: JSON, ETag, Last-Modified."""
    patch_minimal_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            body={"data": [{"symbol": "AAPL"}]},
            headers={"ETag": "abc", "Last-Modified": "lm"},
        )

    class FakeClient:
        async def get(self, *a: Any, **kw: Any) -> FakeResponse:
            return await fake_get(*a, **kw)

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="https://example.com", access_key="X")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    payload, etag, last_mod = await client._observe_call(
        op="eod",
        interval="1d",
        path="/eod",
        params={"symbols": "AAPL"},
        etag=None,
        if_modified_since=None,
    )

    assert payload["data"][0]["symbol"] == "AAPL"
    assert etag == "abc"
    assert last_mod == "lm"


@pytest.mark.anyio
async def test_observe_call_304(monkeypatch: pytest.MonkeyPatch) -> None:
    """304 Not Modified → empty payload, ETag + Last-Modified preserved."""
    patch_minimal_metrics(monkeypatch)
    patch_retry_passthrough(monkeypatch)

    async def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            304,
            body=None,
            headers={"ETag": "E123", "Last-Modified": "L456"},
        )

    class FakeClient:
        async def get(self, *a: Any, **kw: Any) -> FakeResponse:
            return await fake_get(*a, **kw)

        async def aclose(self) -> None:
            return None

        is_closed: bool = False
        headers: dict[str, str] = {}

    settings = MarketstackSettings(base_url="https://example.com", access_key="X")
    client = MarketstackClient(settings, http=FakeClient(), breaker=FakeBreaker())

    payload, etag, last_mod = await client._observe_call(
        op="eod",
        interval="1d",
        path="/eod",
        params={},
        etag="OLD",
        if_modified_since=None,
    )

    assert payload == {}
    assert etag == "E123"
    assert last_mod == "L456"
