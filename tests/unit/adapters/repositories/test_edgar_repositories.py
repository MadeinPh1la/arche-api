# tests/unit/adapters/repositories/test_edgar_repositories.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""
Unit tests for EDGAR repositories.

Covers:
    - EdgarFilingsRepository.upsert_filing + get_filing_by_accession
    - EdgarStatementsRepository.latest_statement_version_for_company
    - EdgarStatementsRepository.list_statement_versions_for_company
    - EdgarStatementsRepository.update_normalized_payload round-trip behavior

These tests run against a real Postgres test database defined by TEST_DATABASE_URL.
They create the minimal schemas/tables required via SQLAlchemy metadata and do
not depend on Alembic migrations.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.adapters.repositories.edgar_filings_repository import (
    EdgarFilingsRepository,
)
from stacklion_api.adapters.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.infrastructure.database.models.base import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
)


async def _prepare_database(engine: AsyncEngine) -> None:
    """Ensure required schemas and tables exist for tests."""
    async with engine.begin() as conn:
        # Make schemas idempotently.
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ref"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sec"))

        # Create all tables (ref + sec + anything else registered).
        await conn.run_sync(Base.metadata.create_all)


def _make_edgar_filing(
    *,
    accession_id: str,
    cik: str,
    ticker: str | None = None,
    company_name: str = "Test Co",
    filing_type: FilingType = FilingType.FORM_10K,
    filing_date: date = date(2024, 1, 31),
    period_end_date: date | None = date(2023, 12, 31),
    accepted_at: datetime | None = datetime(2024, 1, 31, 12, 0, tzinfo=UTC),
    is_amendment: bool = False,
    amendment_sequence: int | None = None,
    primary_document: str | None = "test10k.htm",
) -> EdgarFiling:
    """Helper to construct a valid EdgarFiling."""
    company = EdgarCompanyIdentity(
        cik=cik,
        ticker=ticker,
        legal_name=company_name,
        exchange="NYSE",
        country="US",
    )
    return EdgarFiling(
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


def _make_statement_version(
    *,
    filing: EdgarFiling,
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    accounting_standard: AccountingStandard = AccountingStandard.US_GAAP,
    statement_date: date | None = None,
    fiscal_year: int | None = None,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    currency: str = "USD",
    is_restated: bool = False,
    restatement_reason: str | None = None,
    version_source: str = "EDGAR_PRIMARY",
    version_sequence: int = 1,
) -> EdgarStatementVersion:
    """Helper to construct a valid EdgarStatementVersion."""
    statement_date = statement_date or filing.period_end_date or filing.filing_date
    fiscal_year = fiscal_year or statement_date.year

    return EdgarStatementVersion(
        company=filing.company,
        filing=filing,
        statement_type=statement_type,
        accounting_standard=accounting_standard,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency=currency,
        is_restated=is_restated,
        restatement_reason=restatement_reason,
        version_source=version_source,
        version_sequence=version_sequence,
        accession_id=filing.accession_id,
        filing_date=filing.filing_date,
    )


async def _seed_statement_versions_for_company(
    *,
    session: AsyncSession,
    cik: str,
    company_name: str,
    filing_accession: str,
) -> None:
    """Seed one or more statement versions for a given company/filing.

    This uses the real repositories so we exercise both the upsert and query
    paths while keeping the test logic explicit and deterministic.
    """
    # Reconstruct a minimal domain filing that matches the already-upserted
    # sec.filings row for the given accession.
    filing = _make_edgar_filing(
        accession_id=filing_accession,
        cik=cik,
        company_name=company_name,
    )

    # Seed a couple of statement versions for the same company/type/year.
    v1 = _make_statement_version(
        filing=filing,
        statement_type=StatementType.BALANCE_SHEET,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        is_restated=False,
    )
    v2 = _make_statement_version(
        filing=filing,
        statement_type=StatementType.BALANCE_SHEET,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=2,
        is_restated=True,
        restatement_reason="Updated figures",
    )

    statements_repo = EdgarStatementsRepository(session=session)
    await statements_repo.upsert_statement_versions([v1, v2])


@pytest.mark.anyio
async def test_edgar_filings_repository_upsert_and_get_by_accession() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    await _prepare_database(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        # Ensure ref.companies schema/table exists for these repository tests.
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS ref"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ref.companies (
                    company_id UUID PRIMARY KEY,
                    name       VARCHAR NOT NULL,
                    cik        VARCHAR NOT NULL UNIQUE
                )
                """
            )
        )

        cik = "0000123456"

        # Make sure there is a ref.companies row for this CIK WITHOUT ever
        # changing an existing primary key (avoids FK violations from filings).
        existing_company_id_result = await session.execute(
            text(
                """
                SELECT company_id
                FROM ref.companies
                WHERE cik = :cik
                """
            ),
            {"cik": cik},
        )
        existing_company_id: UUID | None = existing_company_id_result.scalar_one_or_none()

        if existing_company_id is None:
            company_id = uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO ref.companies (company_id, name, cik)
                    VALUES (:company_id, :name, :cik)
                    ON CONFLICT (cik) DO NOTHING
                    """
                ),
                {"company_id": company_id, "name": "Test Co", "cik": cik},
            )
            company_id_for_assert = company_id
        else:
            company_id_for_assert = existing_company_id

        await session.commit()

        repo = EdgarFilingsRepository(session=session)

        accession_id = "0000123456-24-000001"
        filing = _make_edgar_filing(
            accession_id=accession_id,
            cik=cik,
            company_name="Test Co",
            primary_document="test10k.htm",
        )

        # Upsert and fetch.
        await repo.upsert_filing(filing)

        fetched = await repo.get_by_accession(accession=accession_id)
        assert fetched is not None
        assert fetched.accession == accession_id
        assert fetched.cik == cik
        # The repository must point at whatever company_id is in ref.companies,
        # whether it pre-existed or we just inserted it.
        assert fetched.company_id == company_id_for_assert


@pytest.mark.anyio
async def test_edgar_statements_repository_latest_and_list_versions() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    await _prepare_database(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        cik = "0000987654"

        # Make sure there is a ref.companies row for this CIK WITHOUT changing PK.
        existing_company_id_result = await session.execute(
            text(
                """
                SELECT company_id
                FROM ref.companies
                WHERE cik = :cik
                """
            ),
            {"cik": cik},
        )
        existing_company_id: UUID | None = existing_company_id_result.scalar_one_or_none()

        if existing_company_id is None:
            company_id = uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO ref.companies (company_id, name, cik)
                    VALUES (:company_id, :name, :cik)
                    ON CONFLICT (cik) DO NOTHING
                    """
                ),
                {"company_id": company_id, "name": "Example Corp", "cik": cik},
            )

        await session.commit()

        # Seed base filing.
        accession_id = "0000987654-24-000010"
        base_filing = _make_edgar_filing(
            accession_id=accession_id,
            cik=cik,
            company_name="Example Corp",
        )

        filings_repo = EdgarFilingsRepository(session=session)
        await filings_repo.upsert_filings([base_filing])

        # Seed statement versions for this company/filing.
        await _seed_statement_versions_for_company(
            session=session,
            cik=cik,
            company_name="Example Corp",
            filing_accession=accession_id,
        )

        statements_repo = EdgarStatementsRepository(session=session)

        latest = await statements_repo.latest_statement_version_for_company(
            cik=cik,
            statement_type=StatementType.BALANCE_SHEET,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
        )
        assert latest is not None
        # Domain-level assertion: we got the right company + filing back.
        assert latest.company.cik == cik
        assert latest.filing.accession_id == accession_id

        versions = await statements_repo.list_statement_versions_for_company(
            cik=cik,
            statement_type=StatementType.BALANCE_SHEET,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
        )
        assert len(versions) >= 1
        assert versions[0].company.cik == cik


@pytest.mark.anyio
async def test_edgar_statements_repository_latest_missing_returns_none() -> None:
    """When no statement versions exist, latest_* should return None, not blow up."""
    engine = create_async_engine(TEST_DATABASE_URL)
    await _prepare_database(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        cik = "0000000001"
        company_id = uuid4()

        # Seed reference company with no statement versions (idempotent).
        await session.execute(
            text(
                """
                INSERT INTO ref.companies (company_id, name, cik)
                VALUES (:company_id, :name, :cik)
                ON CONFLICT (cik) DO NOTHING
                """
            ),
            {
                "company_id": company_id,
                "name": "No Statements Inc",
                "cik": cik,
            },
        )
        await session.commit()

        statements_repo = EdgarStatementsRepository(session=session)

        latest = await statements_repo.latest_statement_version_for_company(
            cik=cik,
            statement_type=StatementType.BALANCE_SHEET,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
        )
        assert latest is None


@pytest.mark.anyio
async def test_edgar_statements_repository_update_normalized_payload_round_trip() -> None:
    """Normalized payloads can be updated and read back as canonical payloads."""
    engine = create_async_engine(TEST_DATABASE_URL)
    await _prepare_database(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        cik = "0000987655"

        # Ensure ref.companies row exists for this CIK without changing PK.
        existing_company_id_result = await session.execute(
            text(
                """
                SELECT company_id
                FROM ref.companies
                WHERE cik = :cik
                """
            ),
            {"cik": cik},
        )
        existing_company_id: UUID | None = existing_company_id_result.scalar_one_or_none()

        if existing_company_id is None:
            company_id = uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO ref.companies (company_id, name, cik)
                    VALUES (:company_id, :name, :cik)
                    ON CONFLICT (cik) DO NOTHING
                    """
                ),
                {"company_id": company_id, "name": "Normalized Corp", "cik": cik},
            )

        await session.commit()

        # Seed base filing.
        accession_id = "0000987655-24-000011"
        base_filing = _make_edgar_filing(
            accession_id=accession_id,
            cik=cik,
            company_name="Normalized Corp",
        )

        filings_repo = EdgarFilingsRepository(session=session)
        await filings_repo.upsert_filings([base_filing])

        # Seed statement versions for this company/filing.
        await _seed_statement_versions_for_company(
            session=session,
            cik=cik,
            company_name="Normalized Corp",
            filing_accession=accession_id,
        )

        statements_repo = EdgarStatementsRepository(session=session)

        # Build a simple canonical payload to attach to version_sequence=2.
        statement_date = base_filing.period_end_date or base_filing.filing_date
        payload = CanonicalStatementPayload(
            cik=cik,
            statement_type=StatementType.BALANCE_SHEET,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=statement_date,
            fiscal_year=statement_date.year,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            unit_multiplier=0,
            core_metrics={
                CanonicalStatementMetric.TOTAL_ASSETS: Decimal("1000"),
            },
            extra_metrics={
                "CUSTOM_METRIC": Decimal("42.5"),
            },
            dimensions={
                "consolidation": "CONSOLIDATED",
            },
            source_accession_id=accession_id,
            source_taxonomy="US_GAAP_TEST",
            source_version_sequence=2,
        )

        await statements_repo.update_normalized_payload(
            company_cik=cik,
            accession_id=accession_id,
            statement_type=StatementType.BALANCE_SHEET,
            version_sequence=2,
            payload=payload,
            payload_version="v1",
        )

        # Fetch latest and ensure the normalized payload round-trips correctly.
        # NOTE: Seeded versions use fiscal_year=2024, so we must query 2024
        # here rather than statement_date.year (which is 2023).
        latest = await statements_repo.latest_statement_version_for_company(
            cik=cik,
            statement_type=StatementType.BALANCE_SHEET,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
        )
        assert latest is not None
        assert latest.normalized_payload is not None

        np = latest.normalized_payload
        assert np.cik == cik
        assert np.statement_type == StatementType.BALANCE_SHEET
        assert np.core_metrics[CanonicalStatementMetric.TOTAL_ASSETS] == Decimal("1000")
        assert np.extra_metrics["CUSTOM_METRIC"] == Decimal("42.5")
        assert np.source_accession_id == accession_id
        assert np.source_taxonomy == "US_GAAP_TEST"
        assert np.source_version_sequence == 2
