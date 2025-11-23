# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR Types.

Purpose:
    Provide typed response fragments for EDGAR endpoints that this service
    consumes (company submissions, company facts).

Layer:
    infrastructure

Notes:
    These are intentionally partial; we only type fields that are used by the
    ingestion gateway. Additional fields can be added in later phases as needed.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class EdgarRecentFilingsPayload(TypedDict):
    """Normalized recent-filings payload used for staging ingest."""

    cik: str
    filings: list[EdgarRecentFilingRow]


class EdgarRecentFilingRow(TypedDict):
    """Single recent filing row (normalized from SEC submissions JSON)."""

    accession_id: str
    filing_date: str
    period_end_date: NotRequired[str | None]
    form: str
    is_amendment: bool
    primary_document: NotRequired[str | None]
    accepted_at: NotRequired[str | None]


class EdgarSubmissionsRecentSection(TypedDict, total=False):
    """Subset of the 'recent' section from submissions JSON."""

    accessionNumber: list[str]
    filingDate: list[str]
    reportDate: list[str]
    form: list[str]
    primaryDocument: list[str]
    acceptanceDateTime: list[str]


class EdgarSubmissionsRoot(TypedDict, total=False):
    """Subset of the SEC submissions JSON used by the gateway."""

    cik: str
    name: str
    tickers: list[str]
    filings: dict[str, EdgarSubmissionsRecentSection]


class EdgarCompanyFactsRoot(TypedDict, total=False):
    """Subset of EDGAR company facts JSON.

    Currently unused for E2 mapping (metadata-only statement versions), but
    retained for future phases where fact-level modeling is required.
    """

    cik: str
    entityName: str
