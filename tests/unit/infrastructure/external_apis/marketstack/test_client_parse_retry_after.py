from __future__ import annotations

from arche_api.infrastructure.external_apis.marketstack.client import (
    _parse_retry_after,
)


def test_parse_retry_after_valid() -> None:
    assert _parse_retry_after("5") == 5.0


def test_parse_retry_after_invalid() -> None:
    assert _parse_retry_after("abc") is None


def test_parse_retry_after_none() -> None:
    assert _parse_retry_after(None) is None
