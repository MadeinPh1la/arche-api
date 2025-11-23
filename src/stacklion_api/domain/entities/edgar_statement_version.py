# src/stacklion_api/domain/entities/edgar_statement_version.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR financial statement version entity.

Purpose:
    Represent a single version of a financial statement (income, balance sheet,
    cash flow) tied to an EDGAR filing. Encode versioning, restatement
    semantics, and provenance in a modeling-friendly way.

Layer:
    domain

Notes:
    This entity is metadata-centric; it does not carry individual line items.
    Line items and dimensional data will be modeled separately and refer to
    this statement version via identifiers in later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class EdgarStatementVersion:
    """Domain entity representing a versioned financial statement.

    Args:
        company: Company identity associated with this statement.
        filing: EDGAR filing that carries this statement version.
        statement_type: High-level statement taxonomy (income, balance sheet,
            cash flow).
        accounting_standard: Accounting standard (US_GAAP, IFRS, etc.).
        statement_date: Reporting period end date for this statement version.
        fiscal_year: Fiscal year associated with the statement (e.g., 2024).
        fiscal_period: Fiscal period within the year (e.g., Q1, FY).
        currency: ISO-4217 currency code for all monetary values associated with
            this statement version.
        is_restated: Whether this statement represents a restatement of a prior
            version.
        restatement_reason: Human-readable reason for restatement. Must be
            provided when ``is_restated`` is True.
        version_source: Short code describing where this version originates
            (e.g., "EDGAR_PRIMARY", "EDGAR_CORRECTED_FEED").
        version_sequence: Monotonically increasing version number for the
            (company, statement_type, statement_date) tuple.
        accession_id: EDGAR accession ID for convenience lookups; must match the
            associated filing.
        filing_date: Filing date; must match ``filing.filing_date`` for
            consistency.

    Raises:
        EdgarMappingError: If versioning or date invariants are violated.
    """

    company: EdgarCompanyIdentity
    filing: EdgarFiling
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    is_restated: bool
    restatement_reason: str | None
    version_source: str
    version_sequence: int
    accession_id: str
    filing_date: date

    def __post_init__(self) -> None:
        """Validate versioning, date, and provenance invariants."""
        self._validate_dates()
        self._validate_provenance()
        self._validate_version_metadata()

    def _validate_dates(self) -> None:
        """Validate statement and filing dates."""
        if self.statement_date > self.filing_date:
            raise EdgarMappingError(
                "statement_date must be on or before filing_date.",
                details={
                    "statement_date": self.statement_date.isoformat(),
                    "filing_date": self.filing_date.isoformat(),
                },
            )

    def _validate_provenance(self) -> None:
        """Validate provenance fields against the associated filing."""
        if self.filing.accession_id != self.accession_id:
            raise EdgarMappingError(
                "accession_id on statement_version must match associated filing.",
                details={
                    "filing_accession_id": self.filing.accession_id,
                    "statement_accession_id": self.accession_id,
                },
            )

        if self.filing.filing_date != self.filing_date:
            raise EdgarMappingError(
                "filing_date on statement_version must match associated filing.",
                details={
                    "filing_filing_date": self.filing.filing_date.isoformat(),
                    "statement_filing_date": self.filing_date.isoformat(),
                },
            )

    def _validate_version_metadata(self) -> None:
        """Validate versioning, currency, and restatement metadata."""
        if self.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer.",
                details={"fiscal_year": self.fiscal_year},
            )

        if not self.currency.strip():
            raise EdgarMappingError(
                "currency must not be empty.",
                details={"currency": self.currency},
            )

        if self.version_sequence <= 0:
            raise EdgarMappingError(
                "version_sequence must be a positive integer.",
                details={"version_sequence": self.version_sequence},
            )

        normalized_version_source = self.version_source.strip()
        if not normalized_version_source:
            raise EdgarMappingError(
                "version_source must not be empty.",
                details={"version_source": self.version_source},
            )
        object.__setattr__(self, "version_source", normalized_version_source)

        if self.is_restated:
            if self.restatement_reason is None or not self.restatement_reason.strip():
                raise EdgarMappingError(
                    "restatement_reason must be provided when is_restated is True.",
                    details={"restatement_reason": self.restatement_reason},
                )
        else:
            if self.restatement_reason is not None:
                raise EdgarMappingError(
                    "restatement_reason must be None when is_restated is False.",
                    details={"restatement_reason": self.restatement_reason},
                )
