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
            EDGAR accession identifier for the originating filing. Must match
            filing.accession_id exactly.
        filing_date:
            Filing date associated with the originating filing. Must match
            filing.filing_date exactly.
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
    accession_id: str
    filing_date: date

    normalized_payload: CanonicalStatementPayload | None = None
    normalized_payload_version: str | None = None

    def __post_init__(self) -> None:
        """Enforce invariants between the statement version and its filing.

        Validation rules (aligned with domain tests):

        * statement_date must not be after filing.filing_date.
        * accession_id must exactly match filing.accession_id.
        * filing_date must exactly match filing.filing_date.
        * fiscal_year must be a positive integer (> 0).
        * currency must be a non-empty, non-whitespace ISO code.
        * version_source must be a non-empty, non-whitespace string.
        * If is_restated is True, restatement_reason must be non-None.
        * If is_restated is False, restatement_reason must be None.

        Raises:
            EdgarMappingError: If any invariant is violated.
        """
        # 1) statement_date cannot be after the filing date that reported it.
        if self.statement_date > self.filing.filing_date:
            raise EdgarMappingError(
                "statement_date cannot be after filing_date: "
                f"statement_date={self.statement_date}, filing_date={self.filing.filing_date}"
            )

        # 2) accession_id must match the underlying filing metadata.
        if self.accession_id != self.filing.accession_id:
            raise EdgarMappingError(
                "accession_id must match filing.accession_id: "
                f"accession_id={self.accession_id}, filing.accession_id={self.filing.accession_id}"
            )

        # 3) filing_date must match the underlying filing metadata.
        if self.filing_date != self.filing.filing_date:
            raise EdgarMappingError(
                "filing_date must match filing.filing_date: "
                f"filing_date={self.filing_date}, filing.filing_date={self.filing.filing_date}"
            )

        # 4) fiscal_year must be positive (0 is explicitly rejected by tests).
        if self.fiscal_year <= 0:
            raise EdgarMappingError(
                f"fiscal_year must be a positive integer; got {self.fiscal_year}"
            )

        # 5) currency must be a non-empty, non-whitespace ISO code.
        if not self.currency or not self.currency.strip():
            raise EdgarMappingError("currency must be a non-empty ISO code.")

        # 6) version_source must be a non-empty, non-whitespace string.
        if not self.version_source or not self.version_source.strip():
            raise EdgarMappingError(
                "version_source must be a non-empty string describing provenance."
            )

        # 7) Restatement reason consistency:
        #    - If is_restated, restatement_reason must be provided.
        #    - If not restated, restatement_reason must be None.
        if self.is_restated and self.restatement_reason is None:
            raise EdgarMappingError("restatement_reason must be provided when is_restated is True.")

        if not self.is_restated and self.restatement_reason is not None:
            raise EdgarMappingError("restatement_reason must be None when is_restated is False.")


__all__ = ["EdgarStatementVersion"]
