# src/arche_api/domain/entities/edgar_filing.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""EDGAR filing entity.

Purpose:
    Represent a single EDGAR filing (e.g., 10-K, 10-Q, 8-K) in a
    provider-agnostic way. Capture accessions, dates, amendment semantics,
    and core provenance.

Layer:
    domain

Notes:
    This entity does not expose transport details (HTTP URLs, rate limits,
    etc.). Adapters may store raw URLs and document paths separately; here
    we only keep the stable identifiers required for modeling and traceability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.enums.edgar import FilingType
from arche_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class EdgarFiling:
    """Domain entity representing a single EDGAR filing.

    Args:
        accession_id: EDGAR accession number (e.g., "0000320193-24-000012").
        company: Provider-agnostic company identity (CIK, ticker, etc.).
        filing_type: Normalized filing type (e.g., 10-K, 10-Q).
        filing_date: Calendar date when the filing was filed with the SEC.
        period_end_date: Reporting period end date for the filing, where
            applicable.
        accepted_at: Timestamp when the filing was accepted by EDGAR, if known.
        is_amendment: Whether this filing is an amendment to a prior submission.
        amendment_sequence: Amendment sequence number (e.g., 1 for first
            amendment), required when ``is_amendment`` is True.
        primary_document: Optional primary document identifier or filename,
            without assuming any particular URL structure.
        data_source: Provider identifier (e.g., "EDGAR"). Kept as free text so
            the same domain model can support mirrored datasets.

    Raises:
        EdgarMappingError: If invariants such as missing accession ID or an
            invalid amendment configuration are violated.
    """

    accession_id: str
    company: EdgarCompanyIdentity
    filing_type: FilingType
    filing_date: date
    period_end_date: date | None
    accepted_at: datetime | None
    is_amendment: bool
    amendment_sequence: int | None
    primary_document: str | None
    data_source: str = "EDGAR"

    def __post_init__(self) -> None:
        """Validate core filing invariants."""
        self._normalize_accession_id()
        self._validate_dates()
        self._validate_amendment()
        self._validate_data_source()

    def _normalize_accession_id(self) -> None:
        """Normalize and validate the accession ID."""
        normalized_accession = self.accession_id.strip()
        if not normalized_accession:
            raise EdgarMappingError("accession_id must not be empty.")
        object.__setattr__(self, "accession_id", normalized_accession)

    def _validate_dates(self) -> None:
        """Validate filing and period end dates."""
        if self.period_end_date and self.period_end_date > self.filing_date:
            raise EdgarMappingError(
                "period_end_date must be on or before filing_date.",
                details={
                    "period_end_date": self.period_end_date.isoformat(),
                    "filing_date": self.filing_date.isoformat(),
                },
            )

    def _validate_amendment(self) -> None:
        """Validate amendment flags and sequence."""
        if self.is_amendment:
            if self.amendment_sequence is None or self.amendment_sequence <= 0:
                raise EdgarMappingError(
                    "amendment_sequence must be a positive integer for amendments.",
                    details={"amendment_sequence": self.amendment_sequence},
                )
        else:
            if self.amendment_sequence is not None:
                raise EdgarMappingError(
                    "amendment_sequence must be None when is_amendment is False.",
                    details={"amendment_sequence": self.amendment_sequence},
                )

    def _validate_data_source(self) -> None:
        """Validate that the data source identifier is not empty."""
        if not self.data_source.strip():
            raise EdgarMappingError(
                "data_source must not be empty.",
                details={"data_source": self.data_source},
            )
