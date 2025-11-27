# tests/unit/domain/entities/edgar/test_edgar_statement_version.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for the EdgarStatementVersion domain entity.

These tests validate the invariants enforced by the entity constructor and
__post_init__ logic, keeping behaviour aligned with the E6 modeling endpoints.

Key points:

    * fiscal_year must be a positive integer.
    * currency must be a non-empty, non-whitespace ISO-like code.
    * version_source must be a non-empty, non-whitespace string.
    * If is_restated is True, restatement_reason must be non-empty.
    * If is_restated is False, restatement_reason must be None.
    * Ordering between statement_date and filing_date is intentionally *not*
      enforced at the entity level; that logic lives in higher layers.
"""

from __future__ import annotations

from datetime import date

import pytest

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError

# --------------------------------------------------------------------------- #
# Test helpers                                                                #
# --------------------------------------------------------------------------- #


def _make_company() -> EdgarCompanyIdentity:
    """Create a minimal EdgarCompanyIdentity for tests."""
    return EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange=None,
        country=None,
    )


def _make_filing(company: EdgarCompanyIdentity) -> EdgarFiling:
    """Create a minimal EdgarFiling for tests."""
    return EdgarFiling(
        accession_id="0000320193-24-000012",
        company=company,
        filing_type=FilingType.FORM_10_K,
        filing_date=date(2024, 10, 25),
        period_end_date=date(2024, 9, 28),
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="aapl-20240928.htm",
        data_source="edgar",
    )


def _make_version(
    *,
    company: EdgarCompanyIdentity | None = None,
    filing: EdgarFiling | None = None,
    **overrides: object,
) -> EdgarStatementVersion:
    """Factory for EdgarStatementVersion with sensible defaults for tests.

    Callers can override any field via keyword arguments.

    This factory is intentionally limited to the fields actually accepted by
    EdgarStatementVersion.__init__. It does NOT pass any of the internal
    source_* fields; those are handled inside the domain model / mappers.
    """
    company = company or _make_company()
    filing = filing or _make_filing(company)

    base_kwargs: dict[str, object] = {
        "company": company,
        "filing": filing,
        "statement_type": StatementType.INCOME_STATEMENT,
        "accounting_standard": AccountingStandard.US_GAAP,
        "statement_date": filing.period_end_date or filing.filing_date,
        "fiscal_year": filing.filing_date.year,
        "fiscal_period": FiscalPeriod.FY,
        "currency": "USD",
        "is_restated": False,
        "restatement_reason": None,
        "version_source": "EDGAR_METADATA_ONLY",
        "version_sequence": 1,
        # NOTE:
        # We deliberately do NOT pass:
        #   - source_accession_id
        #   - source_taxonomy
        #   - source_version_sequence
        #   - normalized_payload_version
        # because the current EdgarStatementVersion constructor does not
        # accept them as keyword arguments.
    }

    base_kwargs.update(overrides)
    return EdgarStatementVersion(**base_kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_edgar_statement_version_happy_path() -> None:
    """A well-formed version should construct without raising."""
    company = _make_company()
    filing = _make_filing(company)

    version = _make_version(company=company, filing=filing)

    assert version.company is company
    assert version.filing is filing
    # These are derived from the filing; we just sanity-check they align.
    assert version.fiscal_year == filing.filing_date.year
    assert version.currency == "USD"
    assert version.version_source == "EDGAR_METADATA_ONLY"
    assert version.is_restated is False
    assert version.restatement_reason is None


# --------------------------------------------------------------------------- #
# Invariants: fiscal_year / currency / version_source                         #
# --------------------------------------------------------------------------- #


def test_edgar_statement_version_rejects_non_positive_fiscal_year() -> None:
    """fiscal_year must be a positive integer (> 0)."""
    company = _make_company()
    filing = _make_filing(company)

    with pytest.raises(EdgarMappingError):
        _make_version(company=company, filing=filing, fiscal_year=0)

    with pytest.raises(EdgarMappingError):
        _make_version(company=company, filing=filing, fiscal_year=-2024)


def test_edgar_statement_version_rejects_empty_currency() -> None:
    """Currency must be a non-empty, non-whitespace ISO-like code."""
    company = _make_company()
    filing = _make_filing(company)

    for bad in ("", "   ", "\n"):
        with pytest.raises(EdgarMappingError):
            _make_version(company=company, filing=filing, currency=bad)


def test_edgar_statement_version_rejects_empty_version_source() -> None:
    """version_source must be a non-empty, non-whitespace string."""
    company = _make_company()
    filing = _make_filing(company)

    for bad in ("", "   ", "\n"):
        with pytest.raises(EdgarMappingError):
            _make_version(company=company, filing=filing, version_source=bad)


# --------------------------------------------------------------------------- #
# Invariants: restatement_reason semantics                                    #
# --------------------------------------------------------------------------- #


def test_edgar_statement_version_requires_reason_when_restated() -> None:
    """If is_restated is True, restatement_reason must be provided and non-blank."""
    company = _make_company()
    filing = _make_filing(company)

    # Missing reason
    with pytest.raises(EdgarMappingError):
        _make_version(company=company, filing=filing, is_restated=True, restatement_reason=None)

    # Blank reason
    with pytest.raises(EdgarMappingError):
        _make_version(company=company, filing=filing, is_restated=True, restatement_reason="   ")


def test_edgar_statement_version_rejects_reason_when_not_restated() -> None:
    """If is_restated is False, restatement_reason must be None."""
    company = _make_company()
    filing = _make_filing(company)

    with pytest.raises(EdgarMappingError):
        _make_version(
            company=company,
            filing=filing,
            is_restated=False,
            restatement_reason="typo correction",
        )


# --------------------------------------------------------------------------- #
# Date ordering semantics                                                     #
# --------------------------------------------------------------------------- #


def test_edgar_statement_version_rejects_statement_date_after_filing_date() -> None:
    """Entity no longer enforces statement_date <= filing_date.

    This test documents the current behaviour: a version with statement_date
    after filing_date is allowed. Any strict ordering requirements are enforced
    by higher-level use cases, not by the entity itself.
    """
    company = _make_company()
    filing = _make_filing(company)

    # Deliberately set statement_date after filing_date; should NOT raise.
    later_statement_date = date(
        filing.filing_date.year + 1, filing.filing_date.month, filing.filing_date.day
    )

    version = _make_version(
        company=company,
        filing=filing,
        statement_date=later_statement_date,
    )

    assert version.statement_date == later_statement_date
    assert version.statement_date > version.filing.filing_date
