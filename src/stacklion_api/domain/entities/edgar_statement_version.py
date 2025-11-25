# src/stacklion_api/domain/entities/edgar_statement_version.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR statement version domain entity.

Purpose:
    Represent a single version of a financial statement derived from an EDGAR
    filing, including metadata required for deterministic modeling and,
    optionally, a normalized, provider-agnostic payload suitable for
    Bloomberg-class analytics.

Layer:
    domain

Notes:
    - This entity is transport-agnostic and persistence-agnostic.
    - Normalized payloads are modeled via the CanonicalStatementPayload
      value object; earlier phases may have statement versions without a
      normalized payload attached (None).
    - `accession_id` and `filing_date` are accepted as constructor arguments
      (for compatibility with repositories, gateways, and tests) but are
      always validated against and normalized from the attached `filing`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class EdgarStatementVersion:
    """Normalized EDGAR statement version.

    A single version of a financial statement derived from an EDGAR filing,
    with enough metadata to support deterministic modeling and optional
    normalized payloads.

    This entity is the "truth layer" for statement metadata in the domain.
    It enforces invariants between the statement and its underlying filing
    so that downstream repositories and mappers can rely on consistent,
    self-contained records.

    Attributes:
        company: Company identity for which this statement was reported.
        filing: Underlying EDGAR filing metadata this statement is derived from.
        statement_type: Type of statement (income, balance sheet, cash flow, etc.).
        accounting_standard: Accounting standard used (e.g., US_GAAP, IFRS).
        statement_date: Reporting period end date for this statement version.
        fiscal_year: Fiscal year associated with the statement (must be > 0).
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO currency code for reported values (non-empty, trimmed).
        is_restated: Whether this version is a restatement of prior figures.
        restatement_reason:
            Optional reason for restatement. Must be:
                - Non-None when is_restated is True.
                - None when is_restated is False.
        version_source:
            Provenance of this version (e.g., "EDGAR_METADATA_ONLY",
            "EDGAR_XBRL_NORMALIZED"). Must be a non-blank string.
        version_sequence:
            Monotonic sequence number for the version within a given
            (company, statement_type, statement_date) identity tuple.
            Typically 1 for the first version, 2+ for restatements.
        accession_id:
            EDGAR accession identifier for the originating filing. If omitted,
            this is derived from `filing.accession_id`. If provided, it must
            match `filing.accession_id` exactly.
        filing_date:
            Filing date associated with the originating filing. If omitted,
            this is derived from `filing.filing_date`. If provided, it must
            match `filing.filing_date` exactly.
        normalized_payload:
            Optional canonical normalized payload for this statement version.
            This is populated by the Normalized Statement Payload Engine in
            Phase E6-F and may be None for older or metadata-only rows.
        normalized_payload_version:
            Optional version identifier for the normalized payload schema.
            For payloads produced in E6-F, this is expected to be "v1".
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

    # These are accepted as kwargs by all existing code. When omitted or blank,
    # they are derived from `filing` and then validated.
    accession_id: str = ""
    filing_date: date | None = None

    normalized_payload: CanonicalStatementPayload | None = None
    normalized_payload_version: str | None = None

    def __post_init__(self) -> None:
        """Enforce core invariants between the statement version and its filing."""
        self._normalize_and_validate_accession_id()
        self._normalize_and_validate_filing_date()
        self._validate_fiscal_year()
        self._validate_currency()
        self._validate_version_source()
        self._validate_restatement_reason()

    # -------------------------------------------------------------------------
    # Normalization / validation helpers
    # -------------------------------------------------------------------------

    def _normalize_and_validate_accession_id(self) -> None:
        """Derive and validate accession_id against the underlying filing."""
        expected_accession = self.filing.accession_id
        raw_accession = (self.accession_id or "").strip()

        if not raw_accession:
            # Derive when not provided.
            object.__setattr__(self, "accession_id", expected_accession)
            return

        if raw_accession != expected_accession:
            raise EdgarMappingError(
                "accession_id on statement version must match filing.accession_id.",
                details={
                    "statement_accession_id": raw_accession,
                    "filing_accession_id": expected_accession,
                },
            )

        # Normalize whitespace if any.
        object.__setattr__(self, "accession_id", expected_accession)

    def _normalize_and_validate_filing_date(self) -> None:
        """Derive and validate filing_date against the underlying filing."""
        expected_filing_date = self.filing.filing_date

        if self.filing_date is None:
            object.__setattr__(self, "filing_date", expected_filing_date)
            return

        if self.filing_date != expected_filing_date:
            raise EdgarMappingError(
                "filing_date on statement version must match filing.filing_date.",
                details={
                    "statement_filing_date": self.filing_date.isoformat(),
                    "filing_filing_date": expected_filing_date.isoformat(),
                },
            )

    def _validate_fiscal_year(self) -> None:
        """Ensure fiscal_year is a positive integer."""
        if self.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for EdgarStatementVersion.",
                details={"fiscal_year": self.fiscal_year},
            )

    def _validate_currency(self) -> None:
        """Ensure currency is a non-empty ISO code."""
        currency = (self.currency or "").strip()
        if not currency:
            raise EdgarMappingError(
                "currency must be a non-empty ISO code for EdgarStatementVersion.",
                details={"currency": self.currency},
            )

    def _validate_version_source(self) -> None:
        """Ensure version_source is a non-empty, non-whitespace string."""
        version_source = (self.version_source or "").strip()
        if not version_source:
            raise EdgarMappingError(
                "version_source must be a non-empty string for EdgarStatementVersion.",
                details={"version_source": self.version_source},
            )

    def _validate_restatement_reason(self) -> None:
        """Ensure restatement_reason consistency with is_restated flag.

        Rules:
            * If is_restated is True:
                - restatement_reason must be non-None and non-blank.
            * If is_restated is False:
                - restatement_reason must be None.
        """
        if self.is_restated:
            if self.restatement_reason is None or not self.restatement_reason.strip():
                raise EdgarMappingError(
                    "restatement_reason must be provided and non-blank when is_restated is True.",
                    details={"restatement_reason": self.restatement_reason},
                )
            return

        if self.restatement_reason is not None:
            raise EdgarMappingError(
                "restatement_reason must be None when is_restated is False.",
                details={"restatement_reason": self.restatement_reason},
            )


__all__ = ["EdgarStatementVersion"]
