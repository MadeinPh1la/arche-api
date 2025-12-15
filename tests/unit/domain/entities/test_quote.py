from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arche_api.domain.entities.quote import Quote


def test_quote_valid_construction_and_invariants() -> None:
    as_of = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    q = Quote(
        ticker="AAPL",
        price=Decimal("123.45"),
        currency="USD",
        as_of=as_of,
        volume=1_000,
    )

    assert q.ticker == "AAPL"
    assert q.price == Decimal("123.45")
    assert q.currency == "USD"
    assert q.as_of is as_of
    assert q.volume == 1_000


def test_quote_automatically_sets_utc_timezone_when_missing() -> None:
    naive = datetime(2025, 1, 1, 12, 0)  # no tzinfo

    q = Quote(
        ticker="MSFT",
        price=Decimal("100.00"),
        currency="USD",
        as_of=naive,
    )

    assert q.as_of.tzinfo is UTC


@pytest.mark.parametrize(
    "ticker",
    ["", "aapl", "AaPL"],
)
def test_quote_rejects_non_uppercase_or_empty_ticker(ticker: str) -> None:
    with pytest.raises(ValueError, match="ticker must be upper-case non-empty"):
        Quote(
            ticker=ticker,
            price=Decimal("1.0"),
            currency="USD",
            as_of=datetime.now(tz=UTC),
        )


@pytest.mark.parametrize("price", [Decimal("-0.01"), Decimal("-100.0")])
def test_quote_rejects_negative_price(price: Decimal) -> None:
    with pytest.raises(ValueError, match="price must be >= 0"):
        Quote(
            ticker="AAPL",
            price=price,
            currency="USD",
            as_of=datetime.now(tz=UTC),
        )


def test_quote_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="volume must be >= 0"):
        Quote(
            ticker="AAPL",
            price=Decimal("1.0"),
            currency="USD",
            as_of=datetime.now(tz=UTC),
            volume=-1,
        )
