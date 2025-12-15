from __future__ import annotations

import pytest

from arche_api.domain.exceptions.market_data import MarketDataValidationError
from arche_api.infrastructure.external_apis.marketstack.client import (
    MarketstackClient,
)
from arche_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_client_for_paged(monkeypatch, pages: dict[int, tuple[dict, str | None, str | None]]):
    """pages: dict[int, tuple[payload, etag, last_modified]]

    Simulates the internal build(page) callback passed to _paged_all().
    """

    async def build(page: int):
        payload, etag, lm = pages.get(page, ({}, None, None))
        return payload, etag, lm

    settings = MarketstackSettings(base_url="https://x", access_key="y")
    # HTTP client is never used by _paged_all(), so we can pass None.
    client = MarketstackClient(settings, http=None)
    return client, build


# ---------------------------------------------------------------------------
# _paged_all tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_paged_all_single_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """D1 — Single page with data, no pagination.
    Should stop after first page.
    """
    pages = {
        1: ({"data": [{"a": 1}]}, "E1", "LM1"),
    }

    client, build = make_client_for_paged(monkeypatch, pages)

    rows, meta = await client._paged_all(
        endpoint="eod",
        interval="1d",
        build=build,
        page_size=50,
        max_pages=None,
    )

    assert rows == [{"a": 1}]
    assert meta["etag"] == "E1"
    assert meta["last_modified"] == "LM1"


@pytest.mark.anyio
async def test_paged_all_two_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """D2 — Multi-page concatenation until a page returns empty data."""
    pages = {
        1: ({"data": [{"x": 1}]}, "E1", "LM1"),
        2: ({"data": [{"x": 2}]}, None, None),
        3: ({"data": []}, None, None),
    }

    client, build = make_client_for_paged(monkeypatch, pages)

    rows, meta = await client._paged_all(
        endpoint="eod",
        interval="1d",
        build=build,
        page_size=50,
        max_pages=None,
    )

    assert rows == [{"x": 1}, {"x": 2}]
    # Only page 1 had ETag / Last-Modified
    assert meta["etag"] == "E1"
    assert meta["last_modified"] == "LM1"


@pytest.mark.anyio
async def test_paged_all_stop_on_total(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3 — pagination.total stops iteration early."""
    pages = {
        1: ({"data": [{"x": 1}], "pagination": {"total": 1}}, "E1", "LM1"),
        # Second page would have more, but should not be reached.
        2: ({"data": [{"x": 2}]}, "E2", "LM2"),
    }

    client, build = make_client_for_paged(monkeypatch, pages)

    rows, meta = await client._paged_all(
        endpoint="eod",
        interval="1d",
        build=build,
        page_size=50,
        max_pages=None,
    )

    assert rows == [{"x": 1}]
    assert meta["etag"] == "E1"
    assert meta["last_modified"] == "LM1"


@pytest.mark.anyio
async def test_paged_all_max_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """D4 — max_pages=1 forces stop after first page, regardless of pagination.total."""
    pages = {
        1: ({"data": [{"x": 1}]}, "E1", None),
        2: ({"data": [{"x": 2}]}, "E2", None),
    }

    client, build = make_client_for_paged(monkeypatch, pages)

    rows, meta = await client._paged_all(
        endpoint="intraday",
        interval="1m",
        build=build,
        page_size=50,
        max_pages=1,
    )

    assert rows == [{"x": 1}]
    assert meta["etag"] == "E1"
    assert "last_modified" not in meta


@pytest.mark.anyio
async def test_paged_all_bad_data_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5 — data exists but is NOT a list.
    Should raise MarketDataValidationError.
    """
    pages = {
        1: ({"data": "not-a-list"}, None, None),
    }

    client, build = make_client_for_paged(monkeypatch, pages)

    with pytest.raises(MarketDataValidationError):
        await client._paged_all(
            endpoint="intraday",
            interval="1m",
            build=build,
            page_size=50,
            max_pages=None,
        )


# NOTE: We do NOT test "bad item in data list" here because _paged_all itself
# does not validate the type of each element — that validation is done by the
# gateway layer (MarketstackGateway._validate_list_payload).


# ---------------------------------------------------------------------------
# Public wrappers: eod_all / intraday_all
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_eod_all_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """E3 — eod_all delegates to _paged_all correctly, concatenating rows.
    We patch the *instance* method to avoid real HTTP and observe parameters.
    """
    captured: dict[str, object] = {}

    async def fake_paged_all(
        *,
        endpoint: str,
        interval: str,
        build,
        page_size: int,
        max_pages: int | None,
    ):
        captured["endpoint"] = endpoint
        captured["interval"] = interval
        captured["page_size"] = page_size
        captured["max_pages"] = max_pages
        # We do NOT call build() to avoid touching _observe_call / HTTP.
        return [{"r": 1}, {"r": 2}], {"etag": "W/123"}

    client = MarketstackClient(
        MarketstackSettings(base_url="https://x", access_key="y"),
        http=None,
    )

    # Patch the bound method on this instance
    monkeypatch.setattr(client, "_paged_all", fake_paged_all)

    rows, meta = await client.eod_all(
        tickers=["AAPL"],
        date_from="2025-01-01",
        date_to="2025-01-02",
        page_size=2,
    )

    assert rows == [{"r": 1}, {"r": 2}]
    assert meta == {"etag": "W/123"}
    assert captured["endpoint"] == "eod"
    assert captured["interval"] == "1d"
    assert captured["page_size"] == 2
    assert captured["max_pages"] is None


@pytest.mark.anyio
async def test_intraday_all_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """E4 — intraday_all delegates correctly to _paged_all."""
    captured: dict[str, object] = {}

    async def fake_paged_all(
        *,
        endpoint: str,
        interval: str,
        build,
        page_size: int,
        max_pages: int | None,
    ):
        captured["endpoint"] = endpoint
        captured["interval"] = interval
        captured["page_size"] = page_size
        captured["max_pages"] = max_pages
        return [{"r": "x"}], {"etag": "W/ABC"}

    client = MarketstackClient(
        MarketstackSettings(base_url="https://x", access_key="y"),
        http=None,
    )

    monkeypatch.setattr(client, "_paged_all", fake_paged_all)

    rows, meta = await client.intraday_all(
        tickers=["MSFT"],
        date_from="2025-01-01T00:00:00Z",
        date_to="2025-01-01T01:00:00Z",
        interval="1min",
        page_size=100,
    )

    assert rows == [{"r": "x"}]
    assert meta == {"etag": "W/ABC"}
    assert captured["endpoint"] == "intraday"
    assert captured["interval"] == "1min"
    assert captured["page_size"] == 100
    assert captured["max_pages"] is None
