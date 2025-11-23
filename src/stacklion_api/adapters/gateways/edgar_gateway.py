# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Adapter Gateway: EDGAR → domain ingestion.

Purpose:
    Implement the domain-level EDGAR ingestion gateway interface on top of the
    resilient EDGAR HTTP client. Provide:

    * Company identity lookup.
    * Filing header normalization for a company and date range.
    * Metadata-only statement version construction for requested statement types.
    * Raw recent-filings fetch for the bootstrap ingest use case.

Layer:
    adapters
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, cast

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.gateways.edgar_ingestion_gateway import EdgarIngestionGateway
from stacklion_api.infrastructure.external_apis.edgar.client import EdgarClient
from stacklion_api.infrastructure.external_apis.edgar.types import (
    EdgarRecentFilingRow,
    EdgarSubmissionsRecentSection,
    EdgarSubmissionsRoot,
)

logger = logging.getLogger(__name__)


class HttpEdgarIngestionGateway(EdgarIngestionGateway):
    """HTTP-based EDGAR ingestion gateway implementation."""

    def __init__(self, client: EdgarClient) -> None:
        """Initialize the gateway.

        Args:
            client: Resilient EDGAR HTTP client.
        """
        self._client = client

    # ------------------------------------------------------------------ #
    # Application use-case bootstrap hook
    # ------------------------------------------------------------------ #

    async def fetch_recent_filings(self, *, cik: str, limit: int = 100) -> dict[str, Any]:
        """Fetch recent filings JSON for staging ingest."""
        if not cik.strip():
            raise EdgarMappingError("CIK must not be empty for recent filings.")

        logger.info("edgar.fetch_recent_filings.start", extra={"cik": cik, "limit": limit})

        submissions = await self._client.fetch_recent_filings(cik)
        root = self._ensure_submissions_root(submissions)
        recent = self._extract_recent_section(root)

        rows = self._normalize_recent_filings(recent)
        if limit > 0:
            rows = rows[:limit]

        payload = {
            "cik": root["cik"],
            "filings": [
                {
                    "accession_id": row["accession_id"],
                    "filing_date": row["filing_date"],
                    "period_end_date": row.get("period_end_date"),
                    "form": row["form"],
                    "is_amendment": row["is_amendment"],
                    "primary_document": row.get("primary_document"),
                    "accepted_at": row.get("accepted_at"),
                }
                for row in rows
            ],
        }

        logger.info(
            "edgar.fetch_recent_filings.success",
            extra={"cik": cik, "limit": limit, "filings_count": len(payload["filings"])},
        )
        return payload

    # ------------------------------------------------------------------ #
    # Domain-facing EDGAR ingestion interface
    # ------------------------------------------------------------------ #

    async def fetch_company_identity(self, cik: str) -> EdgarCompanyIdentity:
        """Fetch and normalize the company identity for a given CIK."""
        if not cik.strip():
            raise EdgarMappingError("CIK must not be empty for company identity lookup.")

        logger.info("edgar.fetch_company_identity.start", extra={"cik": cik})

        submissions = await self._client.fetch_company_submissions(cik)
        root = self._ensure_submissions_root(submissions)

        name = root.get("name")
        if not name or not isinstance(name, str):
            raise EdgarMappingError(
                "EDGAR submissions JSON missing 'name' field.",
                details={"cik": root.get("cik")},
            )

        raw_cik = root.get("cik")
        if not raw_cik or not isinstance(raw_cik, str):
            raise EdgarMappingError(
                "EDGAR submissions JSON missing 'cik' field.",
                details={"cik": raw_cik},
            )

        tickers = root.get("tickers") or []
        ticker: str | None = None
        if isinstance(tickers, list) and tickers:
            first = tickers[0]
            if isinstance(first, str) and first.strip():
                ticker = first

        identity = EdgarCompanyIdentity(
            cik=raw_cik,
            ticker=ticker,
            legal_name=name,
            exchange=None,
            country=None,
        )

        logger.info(
            "edgar.fetch_company_identity.success",
            extra={"cik": identity.cik, "ticker": identity.ticker},
        )
        return identity

    async def fetch_filings_for_company(
        self,
        company: EdgarCompanyIdentity,
        filing_types: Sequence[FilingType],
        from_date: date,
        to_date: date,
        include_amendments: bool = True,
        max_results: int | None = None,
    ) -> Sequence[EdgarFiling]:
        """Fetch filings for a company within a date range."""
        if from_date > to_date:
            raise EdgarMappingError(
                "from_date must be on or before to_date.",
                details={"from_date": from_date.isoformat(), "to_date": to_date.isoformat()},
            )

        logger.info(
            "edgar.fetch_filings_for_company.start",
            extra={
                "cik": company.cik,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "filing_types": [ft.value for ft in filing_types],
                "include_amendments": include_amendments,
                "max_results": max_results,
            },
        )

        submissions = await self._client.fetch_company_submissions(company.cik)
        root = self._ensure_submissions_root(submissions)
        recent = self._extract_recent_section(root)
        rows = self._normalize_recent_filings(recent)

        type_set = set(filing_types)
        filings: list[EdgarFiling] = []

        for row in rows:
            form = row["form"]
            is_amendment = row["is_amendment"]

            base_form = form.split("/", 1)[0]
            try:
                filing_type = FilingType(base_form)
            except Exception as exc:  # noqa: BLE001
                raise EdgarMappingError(
                    "Unsupported EDGAR form for FilingType mapping.",
                    details={"form": form},
                ) from exc

            if type_set and filing_type not in type_set:
                continue
            if not include_amendments and is_amendment:
                continue

            filing_date = self._parse_iso_date(row["filing_date"])
            if filing_date < from_date or filing_date > to_date:
                continue

            period_end_date: date | None = None
            period_end_raw = row.get("period_end_date")
            if period_end_raw is not None:
                period_end_date = self._parse_iso_date(period_end_raw)

            accepted_at: datetime | None = None
            accepted_raw = row.get("accepted_at")
            if accepted_raw is not None:
                accepted_at = self._parse_acceptance_datetime(accepted_raw)

            accession_id = row["accession_id"]
            primary_document = row.get("primary_document")

            amendment_sequence: int | None = 1 if is_amendment else None

            filings.append(
                EdgarFiling(
                    accession_id=accession_id,
                    company=company,
                    filing_type=filing_type,
                    filing_date=filing_date,
                    period_end_date=period_end_date,
                    accepted_at=accepted_at,
                    is_amendment=is_amendment,
                    amendment_sequence=amendment_sequence,
                    primary_document=primary_document,
                    data_source="EDGAR",
                )
            )

        filings.sort(key=lambda f: (f.filing_date, f.accession_id))
        filings.reverse()

        if max_results is not None and max_results >= 0:
            filings = filings[:max_results]

        logger.info(
            "edgar.fetch_filings_for_company.success",
            extra={
                "cik": company.cik,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "count": len(filings),
            },
        )
        return filings

    async def fetch_statement_versions_for_filing(
        self,
        filing: EdgarFiling,
        statement_types: Sequence[StatementType],
    ) -> Sequence[EdgarStatementVersion]:
        """Build metadata-only statement versions for a given filing."""
        if not statement_types:
            return []

        statement_date = filing.period_end_date or filing.filing_date
        fiscal_year = statement_date.year
        accounting_standard = AccountingStandard.US_GAAP
        fiscal_period = FiscalPeriod.FY
        currency = "USD"

        versions: list[EdgarStatementVersion] = []
        for idx, st_type in enumerate(statement_types, start=1):
            versions.append(
                EdgarStatementVersion(
                    company=filing.company,
                    filing=filing,
                    statement_type=st_type,
                    accounting_standard=accounting_standard,
                    statement_date=statement_date,
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    currency=currency,
                    is_restated=False,
                    restatement_reason=None,
                    version_source="EDGAR_METADATA_ONLY",
                    version_sequence=idx,
                    accession_id=filing.accession_id,
                    filing_date=filing.filing_date,
                )
            )

        return versions

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ensure_submissions_root(raw: Any) -> EdgarSubmissionsRoot:
        """Validate that the submissions payload has the expected root shape."""
        if not isinstance(raw, dict):
            raise EdgarMappingError(
                "EDGAR submissions payload must be a JSON object.",
                details={"type": type(raw).__name__},
            )

        root = cast(EdgarSubmissionsRoot, raw)
        if "cik" not in root or "filings" not in root:
            raise EdgarIngestionError(
                "EDGAR submissions payload missing required keys.",
                details={"keys": list(root.keys())},
            )
        return root

    @staticmethod
    def _extract_recent_section(root: EdgarSubmissionsRoot) -> EdgarSubmissionsRecentSection:
        """Extract and validate the 'recent' filings section."""
        filings = root.get("filings")
        if not isinstance(filings, dict):
            raise EdgarMappingError(
                "EDGAR submissions 'filings' section must be an object.",
                details={"type": type(filings).__name__},
            )

        recent = filings.get("recent")
        if not isinstance(recent, dict):
            raise EdgarMappingError(
                "EDGAR submissions 'filings.recent' section must be an object.",
                details={"keys": list(filings.keys())},
            )

        return recent

    @staticmethod
    def _normalize_recent_filings(
        recent: EdgarSubmissionsRecentSection,
    ) -> list[EdgarRecentFilingRow]:
        """Normalize the 'recent' section into a list of filing rows."""
        accession_numbers = recent.get("accessionNumber") or []
        filing_dates = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []
        forms = recent.get("form") or []
        primary_docs = recent.get("primaryDocument") or []
        acceptance_times = recent.get("acceptanceDateTime") or []

        n = min(
            len(accession_numbers),
            len(filing_dates),
            len(forms),
        )
        rows: list[EdgarRecentFilingRow] = []
        for idx in range(n):
            acc = accession_numbers[idx]
            form = forms[idx]
            filing_date = filing_dates[idx]
            period_end_date = report_dates[idx] if idx < len(report_dates) else None
            primary_doc = primary_docs[idx] if idx < len(primary_docs) else None
            accepted_at = acceptance_times[idx] if idx < len(acceptance_times) else None

            form_str = str(form)
            is_amendment = form_str.endswith("/A")

            row: EdgarRecentFilingRow = {
                "accession_id": str(acc),
                "filing_date": str(filing_date),
                "period_end_date": period_end_date,
                "form": form_str,
                "is_amendment": is_amendment,
                "primary_document": primary_doc,
                "accepted_at": accepted_at,
            }
            rows.append(row)

        return rows

    @staticmethod
    def _parse_iso_date(value: str) -> date:
        """Parse an ISO date string into a date object."""
        try:
            return date.fromisoformat(value)
        except Exception as exc:  # noqa: BLE001
            raise EdgarMappingError(
                "Invalid ISO date in EDGAR payload.",
                details={"value": value},
            ) from exc

    @staticmethod
    def _parse_acceptance_datetime(value: str) -> datetime:
        """Parse EDGAR acceptance datetime string."""
        try:
            if "-" in value or "T" in value:
                return datetime.fromisoformat(value)
            if len(value) == 14 and value.isdigit():
                year = int(value[0:4])
                month = int(value[4:6])
                day = int(value[6:8])
                hour = int(value[8:10])
                minute = int(value[10:12])
                second = int(value[12:14])
                return datetime(year, month, day, hour, minute, second)
        except Exception as exc:  # noqa: BLE001
            raise EdgarMappingError(
                "Invalid acceptance datetime in EDGAR payload.",
                details={"value": value},
            ) from exc

        raise EdgarMappingError(
            "Unrecognized acceptance datetime format in EDGAR payload.",
            details={"value": value},
        )
