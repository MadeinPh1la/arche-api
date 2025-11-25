from __future__ import annotations

import pytest

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


def test_edgar_company_identity_valid_construction_and_normalization() -> None:
    company = EdgarCompanyIdentity(
        cik=" 0000320193 ",
        ticker="aapl ",
        legal_name="Apple Inc.",
        exchange="Nasdaq",
        country="us",
    )

    assert company.cik == "0000320193"
    assert company.ticker == "AAPL"
    assert company.legal_name == "Apple Inc."
    assert company.exchange == "Nasdaq"
    assert company.country == "US"


@pytest.mark.parametrize("cik", ["", "   ", "ABC123"])
def test_edgar_company_identity_rejects_invalid_cik(cik: str) -> None:
    with pytest.raises(EdgarMappingError):
        EdgarCompanyIdentity(
            cik=cik,
            ticker="AAPL",
            legal_name="Apple Inc.",
            exchange="Nasdaq",
            country="US",
        )


def test_edgar_company_identity_rejects_empty_ticker_when_provided() -> None:
    with pytest.raises(EdgarMappingError):
        EdgarCompanyIdentity(
            cik="0000320193",
            ticker="  ",
            legal_name="Apple Inc.",
            exchange="Nasdaq",
            country="US",
        )


def test_edgar_company_identity_rejects_invalid_country_code() -> None:
    with pytest.raises(EdgarMappingError):
        EdgarCompanyIdentity(
            cik="0000320193",
            ticker="AAPL",
            legal_name="Apple Inc.",
            exchange="Nasdaq",
            country="USA",
        )
