# src/stacklion_api/domain/entities/edgar_company.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR company identity entity.

Purpose:
    Represent a provider-agnostic company identity for EDGAR filings, capturing
    CIK, ticker, legal name, and primary listing metadata for modeling.

Layer:
    domain

Notes:
    This entity is intentionally light; it does not mirror the full EDGAR
    company universe. Invariants are enforced in __post_init__ and violations
    raise EdgarMappingError.
"""

from __future__ import annotations

from dataclasses import dataclass

from stacklion_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class EdgarCompanyIdentity:
    """Provider-agnostic identity for an EDGAR filer.

    Args:
        cik: Central Index Key assigned by the SEC. Must be a non-empty string
            with only digits once normalized (leading zeros allowed).
        ticker: Optional exchange ticker symbol. When provided, stored as
            upper case.
        legal_name: Legal entity name as reported in filings.
        exchange: Optional primary listing venue (e.g., "NYSE", "NASDAQ").
        country: Optional ISO-3166 alpha-2 country code for the primary
            listing jurisdiction.

    Raises:
        EdgarMappingError: If the CIK is empty or invalid, or the optional
            fields are provided in an invalid format.
    """

    cik: str
    ticker: str | None
    legal_name: str
    exchange: str | None
    country: str | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the identity fields."""
        self._validate_and_normalize_cik()
        self._normalize_ticker()
        self._normalize_country()

    def _validate_and_normalize_cik(self) -> None:
        """Validate and normalize the CIK field."""
        normalized_cik = self.cik.strip()
        if not normalized_cik:
            raise EdgarMappingError("CIK must not be empty.")

        if not normalized_cik.isdigit():
            raise EdgarMappingError("CIK must contain only digits.", details={"cik": self.cik})

        object.__setattr__(self, "cik", normalized_cik)

    def _normalize_ticker(self) -> None:
        """Normalize the ticker field when provided."""
        if self.ticker is None:
            return

        cleaned_ticker = self.ticker.strip()
        if not cleaned_ticker:
            raise EdgarMappingError(
                "Ticker, when provided, must not be empty.",
                details={"ticker": self.ticker},
            )
        object.__setattr__(self, "ticker", cleaned_ticker.upper())

    def _normalize_country(self) -> None:
        """Normalize the country field when provided."""
        if self.country is None:
            return

        cleaned_country = self.country.strip().upper()
        if cleaned_country and len(cleaned_country) != 2:
            raise EdgarMappingError(
                "Country must be an ISO-3166 alpha-2 code when provided.",
                details={"country": self.country},
            )
        object.__setattr__(self, "country", cleaned_country or None)
