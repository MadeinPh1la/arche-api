# tests/integration/repositories/test_edgar_statement_alignment_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for the EDGAR statement alignment repository.

These tests operate directly against the database using the
`sec.edgar_statement_alignment` table and the concrete SQLAlchemy-backed
repository implementation.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.adapters.repositories.edgar_statement_alignment_repository import (
    SqlAlchemyEdgarStatementAlignmentRepository,
)
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    StatementAlignmentRecord,
)
from stacklion_api.infrastructure.database.models.ref import Company
from stacklion_api.infrastructure.database.models.sec import (
    EdgarStatementAlignment,
    Filing,
    StatementVersion,
)


@pytest.fixture
async def alignment_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh AsyncSession (and engine) per test.

    Each test gets its own engine and connection pool bound to the same
    event loop. This avoids asyncpg cross-loop issues and allows us to
    create only the tables we need for alignment persistence.
    """
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
    )
    engine: AsyncEngine = create_async_engine(database_url, future=True)

    # Ensure minimal schemas and tables exist for these tests.
    async with engine.begin() as conn:
        # Create namespaced schemas explicitly to match production layout.
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ref"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sec"))

        # ref.companies
        await conn.run_sync(Company.__table__.create, checkfirst=True)
        # sec.filings
        await conn.run_sync(Filing.__table__.create, checkfirst=True)
        # sec.statement_versions
        await conn.run_sync(StatementVersion.__table__.create, checkfirst=True)
        # sec.edgar_statement_alignment
        await conn.run_sync(EdgarStatementAlignment.__table__.create, checkfirst=True)

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with session_factory() as session:
        try:
            yield session
        finally:
            # Always roll back at the end of the test to keep things isolated.
            await session.rollback()

    await engine.dispose()


@dataclass(slots=True)
class TestAlignmentRecord(StatementAlignmentRecord):
    """Simple alignment record used to drive repository calls in tests."""

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: str
    statement_date: date
    version_sequence: int

    # Optional / extended fields consumed via getattr() in the repo.
    fye_date: date | None = None
    is_53_week_year: bool = False
    period_start: date | None = None
    period_end: date | None = None
    alignment_status: str = "ALIGNED"
    is_partial_period: bool = False
    is_off_cycle_period: bool = False
    is_irregular_calendar: bool = False
    details: dict[str, Any] | None = None


async def _seed_company_and_versions(
    session: AsyncSession,
) -> tuple[Company, Sequence[StatementVersion]]:
    """Insert a single company, filing, and a couple of statement_versions.

    CIK and accession are randomized per call to avoid collisions with
    existing integration data and other tests.
    """
    cik = str(uuid4().int % 10**10).zfill(10)
    accession = f"{cik}-{uuid4().hex[:6]}"

    company = Company(  # type: ignore[call-arg]
        company_id=uuid4(),
        cik=cik,
        name="Test Company",
    )
    session.add(company)

    filing = Filing(
        filing_id=uuid4(),
        company_id=company.company_id,
        cik=company.cik,
        accession=accession,
        form_type="10-K",
        filed_at=datetime.utcnow(),
        period_of_report=date(2023, 12, 31),
        filing_metadata=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="10k.htm",
        accepted_at=datetime.utcnow(),
        filing_url=None,
        data_source="EDGAR",
    )
    session.add(filing)
    await session.flush()

    sv1 = StatementVersion(
        statement_version_id=uuid4(),
        company_id=company.company_id,
        filing_id=filing.filing_id,
        statement_type=StatementType.INCOME_STATEMENT.value,
        accounting_standard="US_GAAP",
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY.value,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR",
        version_sequence=1,
        normalized_payload=None,
        normalized_payload_version="v1",
        accession_id=filing.accession,
        filing_date=filing.period_of_report,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    sv2 = StatementVersion(
        statement_version_id=uuid4(),
        company_id=company.company_id,
        filing_id=filing.filing_id,
        statement_type=StatementType.INCOME_STATEMENT.value,
        accounting_standard="US_GAAP",
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY.value,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR",
        version_sequence=2,
        normalized_payload=None,
        normalized_payload_version="v1",
        accession_id=filing.accession,
        filing_date=filing.period_of_report,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    session.add_all([sv1, sv2])
    await session.commit()

    return company, (sv1, sv2)


@pytest.mark.anyio
async def test_upsert_alignment_inserts_row(alignment_session: AsyncSession) -> None:
    """upsert_alignment() must persist a new alignment row for a statement."""
    company, (sv1, _) = await _seed_company_and_versions(alignment_session)
    repo = SqlAlchemyEdgarStatementAlignmentRepository(alignment_session)

    record = TestAlignmentRecord(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=sv1.fiscal_year,
        fiscal_period=sv1.fiscal_period,
        statement_date=sv1.statement_date,
        version_sequence=sv1.version_sequence,
        alignment_status="ALIGNED",
        is_partial_period=False,
        is_off_cycle_period=False,
        is_irregular_calendar=False,
    )

    await repo.upsert_alignment(record)

    result = await alignment_session.execute(select(EdgarStatementAlignment))
    rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.cik == company.cik
    assert row.statement_type == StatementType.INCOME_STATEMENT.value
    assert row.fiscal_year == sv1.fiscal_year
    assert row.fiscal_period == sv1.fiscal_period
    assert row.version_sequence == sv1.version_sequence
    assert row.alignment_status == "ALIGNED"
    assert row.is_partial_period is False
    assert row.is_off_cycle_period is False
    assert row.is_irregular_calendar is False


@pytest.mark.anyio
async def test_upsert_alignments_updates_existing_row(
    alignment_session: AsyncSession,
) -> None:
    """upsert_alignments() must update an existing row, not duplicate it."""
    company, (sv1, _) = await _seed_company_and_versions(alignment_session)
    repo = SqlAlchemyEdgarStatementAlignmentRepository(alignment_session)

    base = TestAlignmentRecord(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=sv1.fiscal_year,
        fiscal_period=sv1.fiscal_period,
        statement_date=sv1.statement_date,
        version_sequence=sv1.version_sequence,
        alignment_status="ALIGNED",
    )

    # First insert.
    await repo.upsert_alignment(base)

    # Second call with same identity but different status/flags should update.
    updated = replace(
        base,
        alignment_status="PARTIAL",
        is_partial_period=True,
    )
    await repo.upsert_alignment(updated)

    result = await alignment_session.execute(select(EdgarStatementAlignment))
    rows = result.scalars().all()

    # Still a single row.
    assert len(rows) == 1
    row = rows[0]
    assert row.alignment_status == "PARTIAL"
    assert row.is_partial_period is True


@pytest.mark.anyio
async def test_list_alignment_timeline_orders_by_year_period_version(
    alignment_session: AsyncSession,
) -> None:
    """list_alignment_timeline_for_company() must return a deterministic timeline."""
    company, (sv1, sv2) = await _seed_company_and_versions(alignment_session)
    repo = SqlAlchemyEdgarStatementAlignmentRepository(alignment_session)

    # Two versions of the same FY period to test version ordering.
    record_v1 = TestAlignmentRecord(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=sv1.fiscal_year,
        fiscal_period=sv1.fiscal_period,
        statement_date=sv1.statement_date,
        version_sequence=sv1.version_sequence,
        alignment_status="ALIGNED",
    )
    record_v2 = TestAlignmentRecord(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=sv2.fiscal_year,
        fiscal_period=sv2.fiscal_period,
        statement_date=sv2.statement_date,
        version_sequence=sv2.version_sequence,
        alignment_status="ALIGNED",
    )

    await repo.upsert_alignments([record_v2, record_v1])

    timeline = await repo.list_alignment_timeline_for_company(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.INCOME_STATEMENT,
    )

    # Expect increasing version_sequence order for the same period.
    assert [row.version_sequence for row in timeline] == [1, 2]
    assert all(row.cik == company.cik for row in timeline)
    assert all(row.statement_type == StatementType.INCOME_STATEMENT.value for row in timeline)
