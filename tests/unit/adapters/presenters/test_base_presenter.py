# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for BasePresenter behaviors and helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import Response

from stacklion_api.adapters.presenters.base_presenter import (
    BasePresenter,
    PresentResult,
    _compute_quoted_etag,
    _json_default,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    PaginatedEnvelope,
    SuccessEnvelope,
)


class _DummyPresenter(BasePresenter[dict]):
    """Concrete subclass for testing BasePresenter helpers."""

    pass


def test_present_success_sets_quoted_etag_and_traces() -> None:
    p = _DummyPresenter()

    res = p.present_success(data={"x": 1}, trace_id="abc-123")
    assert isinstance(res.body, SuccessEnvelope)
    assert res.body.data == {"x": 1}

    # headers: X-Request-ID present
    assert res.headers.get("X-Request-ID") == "abc-123"

    # ETag: quoted, 64-hex strong tag
    etag = res.headers.get("ETag")
    assert (
        etag is not None
        and etag.startswith('"')
        and etag.endswith('"')
        and len(etag.strip('"')) == 64
    )

    assert res.status_code is None


def test_present_error_sets_status_and_trace_no_etag() -> None:
    p = _DummyPresenter()
    res = p.present_error(
        code="VALIDATION_ERROR",
        http_status=400,
        message="nope",
        trace_id="rid-1",
        details={"f": "t"},
    )

    assert isinstance(res.body, ErrorEnvelope)
    err = res.body.error
    assert err.code == "VALIDATION_ERROR"
    assert err.http_status == 400
    assert err.message == "nope"
    assert err.details == {"f": "t"}
    assert err.trace_id == "rid-1"

    # No ETag for errors; X-Request-ID echoed; status set
    assert res.headers == {"X-Request-ID": "rid-1"}
    assert res.status_code == 400


def test_present_paginated_passes_through_etag_and_does_not_invent() -> None:
    p = _DummyPresenter()

    with_etag = p.present_paginated(
        items=[{"i": 1}], page=1, page_size=10, total=1, trace_id="t-1", etag='W/"abc"'
    )
    assert isinstance(with_etag.body, PaginatedEnvelope)
    assert with_etag.headers == {"X-Request-ID": "t-1", "ETag": 'W/"abc"'}

    without_etag = p.present_paginated(
        items=[], page=1, page_size=10, total=0, trace_id="t-2", etag=None
    )
    assert isinstance(without_etag.body, PaginatedEnvelope)
    # Should NOT invent an ETag
    assert without_etag.headers == {"X-Request-ID": "t-2"}


def test_apply_headers_overwrites_and_sets_status() -> None:
    p = _DummyPresenter()
    result = PresentResult(
        body={"ok": True},
        headers={"ETag": '"NEW"', "Cache-Control": "max-age=60"},
        status_code=304,
    )
    response = Response(headers={"ETag": '"OLD"', "X-Existing": "1"})

    p.apply_headers(result, response)

    # Overwrite behavior per BasePresenter implementation
    assert response.headers["ETag"] == '"NEW"'
    # Preserve unrelated headers and add new ones
    assert response.headers["X-Existing"] == "1"
    assert response.headers["Cache-Control"] == "max-age=60"
    assert response.status_code == 304


# ---- helper coverage: _json_default and _compute_quoted_etag -----------------


def test__json_default_supported_types() -> None:
    dt = datetime(2025, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert _json_default(dt).startswith("2025-01-02T03:04:05.123456")

    d = date(2025, 1, 2)
    assert _json_default(d) == "2025-01-02"

    # Canonicalized: no insignificant zeros, no scientific notation
    assert _json_default(Decimal("123.4500")) == "123.45"
    assert _json_default(Decimal("100.00")) == "100"  # exact integer collapses
    assert _json_default(Decimal("-0.0")) == "0"  # collapse negative zero


def test__json_default_unsupported_type_raises() -> None:
    with pytest.raises(TypeError):
        _json_default(object())


def test__compute_quoted_etag_yields_quoted_hex_digest() -> None:
    payload = {"a": 1, "b": Decimal("1.00"), "t": datetime(2025, 1, 1, tzinfo=UTC)}
    etag = _compute_quoted_etag(payload)
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag.strip('"')) == 64  # sha256 hex


def test_present_success_etag_deterministic_for_semantically_equal_values() -> None:
    p = BasePresenter()

    payload1 = {
        "s": "x",
        "n": Decimal("1.50"),
        "ts": datetime(2025, 1, 2, tzinfo=UTC),
    }
    payload2 = {
        "s": "x",
        "n": Decimal("1.500"),  # same numeric value, different repr
        "ts": datetime(2025, 1, 2, tzinfo=UTC),  # identical timestamp
    }

    e1 = p.present_success(data=payload1).headers["ETag"]
    e2 = p.present_success(data=payload2).headers["ETag"]
    assert e1 == e2  # canonical JSON hashing stable
