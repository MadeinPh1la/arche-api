# tests/integration/repositories/test_edgar_reconciliation_checks_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for the EDGAR reconciliation checks repository.

These tests operate directly against the database using the
`sec.edgar_reconciliation_checks` table and the concrete SQLAlchemy-backed
repository implementation.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.adapters.repositories.edgar_reconciliation_checks_repository import (
    SqlAlchemyEdgarReconciliationChecksRepository,
)
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_reconciliation import ReconciliationResult
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from stacklion_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from stacklion_api.infrastructure.database.models.ref import Company
from stacklion_api.infrastructure.database.models.sec import (
    EdgarReconciliationCheck,
    Filing,
    StatementVersion,
)


@pytest.fixture
async def recon_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh AsyncSession (and engine) per test.

    Each test gets its own engine and connection pool bound to the same
    event loop. This avoids asyncpg cross-loop issues and allows us to
    create only the tables we need for reconciliation ledger persistence.
    """
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
    )
    engine: AsyncEngine = create_async_engine(database_url, future=True)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ref"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sec"))

        await conn.run_sync(Company.__table__.create, checkfirst=True)
        await conn.run_sync(Filing.__table__.create, checkfirst=True)
        await conn.run_sync(StatementVersion.__table__.create, checkfirst=True)
        await conn.run_sync(EdgarReconciliationCheck.__table__.create, checkfirst=True)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


async def _seed_company_and_statement_version(
    session: AsyncSession,
) -> tuple[Company, StatementVersion]:
    """Insert a company, filing, and statement_version for reconciliation tests."""
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
        period_of_report=date(2024, 12, 31),
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

    sv = StatementVersion(
        statement_version_id=uuid4(),
        company_id=company.company_id,
        filing_id=filing.filing_id,
        statement_type=StatementType.BALANCE_SHEET.value,
        accounting_standard="US_GAAP",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
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

    session.add(sv)
    await session.commit()
    return company, sv


@pytest.mark.anyio
async def test_append_and_list_for_statement_orders_by_rule_identity(
    recon_session: AsyncSession,
) -> None:
    """list_for_statement() must return deterministic ordering by rule identity."""
    company, sv = await _seed_company_and_statement_version(recon_session)
    repo = SqlAlchemyEdgarReconciliationChecksRepository(recon_session)

    identity = NormalizedStatementIdentity(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=sv.fiscal_year,
        fiscal_period=FiscalPeriod(sv.fiscal_period),
        version_sequence=sv.version_sequence,
    )

    run_id = str(uuid4())
    executed_at = datetime.utcnow()

    results: Sequence[ReconciliationResult] = [
        ReconciliationResult(
            statement_identity=identity,
            rule_id="Z_LAST",
            rule_category=ReconciliationRuleCategory.IDENTITY,
            status=ReconciliationStatus.PASS,
            severity=MaterialityClass.NONE,
            expected_value=None,
            actual_value=None,
            delta=None,
            dimension_key=None,
            dimension_labels=None,
            notes=None,
        ),
        ReconciliationResult(
            statement_identity=identity,
            rule_id="A_FIRST",
            rule_category=ReconciliationRuleCategory.IDENTITY,
            status=ReconciliationStatus.FAIL,
            severity=MaterialityClass.HIGH,
            expected_value=Decimal("100"),
            actual_value=Decimal("90"),
            delta=Decimal("-10"),
            dimension_key="segment:consolidated",
            dimension_labels={"segment": "Consolidated"},
            notes={"tolerance": "0.01"},
        ),
    ]

    await repo.append_results(
        reconciliation_run_id=run_id,
        executed_at=executed_at,
        results=results,
    )
    await recon_session.commit()

    out = await repo.list_for_statement(identity=identity, reconciliation_run_id=run_id)

    assert [r.rule_id for r in out] == ["A_FIRST", "Z_LAST"]
    assert out[0].dimension_key == "segment:consolidated"
    assert out[0].expected_value == Decimal("100")
    assert out[0].actual_value == Decimal("90")
    assert out[0].delta == Decimal("-10")


@pytest.mark.anyio
async def test_list_for_window_returns_year_slice(
    recon_session: AsyncSession,
) -> None:
    """list_for_window() must return a deterministic timeline slice."""
    company, sv = await _seed_company_and_statement_version(recon_session)
    repo = SqlAlchemyEdgarReconciliationChecksRepository(recon_session)

    identity = NormalizedStatementIdentity(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=sv.fiscal_year,
        fiscal_period=FiscalPeriod(sv.fiscal_period),
        version_sequence=sv.version_sequence,
    )

    run_id = str(uuid4())
    executed_at = datetime.utcnow()

    await repo.append_results(
        reconciliation_run_id=run_id,
        executed_at=executed_at,
        results=[
            ReconciliationResult(
                statement_identity=identity,
                rule_id="BS_TEST_RULE",
                rule_category=ReconciliationRuleCategory.IDENTITY,
                status=ReconciliationStatus.PASS,
                severity=MaterialityClass.NONE,
                expected_value=None,
                actual_value=None,
                delta=None,
                dimension_key=None,
                dimension_labels=None,
                notes=None,
            )
        ],
    )
    await recon_session.commit()

    window = await repo.list_for_window(
        cik=company.cik,  # type: ignore[arg-type]
        statement_type=StatementType.BALANCE_SHEET.value,
        fiscal_year_from=2024,
        fiscal_year_to=2024,
        limit=1000,
    )

    assert len(window) >= 1
    assert all(r.statement_identity.cik == company.cik for r in window)
    assert all(r.statement_identity.fiscal_year == 2024 for r in window)
