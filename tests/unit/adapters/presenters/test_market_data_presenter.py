# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for MarketDataPresenter and helpers."""

from __future__ import annotations

import pytest
from fastapi import Response

from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.presenters.market_data_presenter import (
    MarketDataPresenter,
    _normalize_if_none_match,
)
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ('  "abc"  ', '"abc"'),
        ('W/"abc"', '"abc"'),
        ('  W/  "abc"  ', '"abc"'),
        ('"already-strong"', '"already-strong"'),
    ],
)
def test_normalize_if_none_match(raw: str | None, expected: str | None) -> None:
    assert _normalize_if_none_match(raw) == expected


def test_present_list_builds_paginated_envelope() -> None:
    presenter = MarketDataPresenter()
    result = presenter.present_list(items=[{"t": 1}], page=2, page_size=5, total=11)

    assert isinstance(result.body, PaginatedEnvelope)
    assert result.body.page == 2
    assert result.body.page_size == 5
    assert result.body.total == 11
    assert result.body.items == [{"t": 1}]
    assert result.headers == {}  # no ETag here


@pytest.mark.anyio
async def test_present_list_with_etag_returns_200_and_sets_header() -> None:
    presenter = MarketDataPresenter()

    items = [{"a": 1}]
    res = presenter.present_list_with_etag(
        items=items, page=1, page_size=1, total=1, if_none_match='"different"'
    )

    assert isinstance(res.body, PaginatedEnvelope)
    assert res.status_code is None  # 200 path
    etag = res.headers.get("ETag")
    # Strong, quoted SHA-256 hex (64 chars) is expected
    assert (
        etag is not None
        and etag.startswith('"')
        and etag.endswith('"')
        and len(etag.strip('"')) == 64
    )
    assert res.body.items == items


@pytest.mark.anyio
async def test_present_list_with_etag_returns_304_when_tag_matches() -> None:
    presenter = MarketDataPresenter()

    # Build the exact payload hashed by presenter
    payload = {"page": 1, "page_size": 1, "total": 1, "items": [{"x": 1}]}
    # Import the internal helper just for the test to compute the expected strong tag
    from stacklion_api.adapters.presenters.market_data_presenter import (  # type: ignore
        _compute_quoted_etag as _hash,
    )

    expected = _hash(payload)  # e.g., '"abcdef..."' (quoted, strong)

    res = presenter.present_list_with_etag(
        items=payload["items"],
        page=payload["page"],
        page_size=payload["page_size"],
        total=payload["total"],
        if_none_match=f"W/{expected}",  # weak variant must normalize and match
    )

    assert res.status_code == 304
    assert res.body is None
    assert res.headers.get("ETag") == expected


def test_finalize_applies_headers_and_status_code() -> None:
    presenter = MarketDataPresenter()
    result = PresentResult(body={"ok": True}, headers={"ETag": '"Z"'}, status_code=304)

    response = Response()
    body = presenter.finalize(result, response)

    assert body == {"ok": True}
    assert response.status_code == 304
    assert response.headers["ETag"] == '"Z"'
