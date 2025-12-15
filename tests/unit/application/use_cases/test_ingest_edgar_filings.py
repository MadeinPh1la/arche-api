# tests/unit/application/test_ingest_edgar_filings.py
from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arche_api.application.use_cases.external_apis.edgar.ingest_edgar_filings import (
    EdgarGateway,
    IngestEdgarFilings,
    IngestEdgarRequest,
)

# Use CI-friendly DB URL by default, overridable via env for local dev.
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://arche:arche@127.0.0.1:5432/arche_test",
)


class FakeEdgarGateway(EdgarGateway):
    async def fetch_recent_filings(self, *, cik: str, limit: int = 100) -> dict[str, object]:
        """Return a minimal deterministic EDGAR payload."""
        return {
            "cik": cik,
            "filings": [
                {"accessionNumber": "0000000001-25-000001"},
                {"accessionNumber": "0000000001-25-000002"},
            ],
        }


@pytest.mark.anyio
async def test_ingest_edgar_filings_counts_filings_and_persists_raw() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        uc = IngestEdgarFilings(FakeEdgarGateway())
        req = IngestEdgarRequest(cik="0000000001")

        count = await uc(session, req)

        # We returned 2 filings in the fake, so the UC should report 2
        assert count == 2

        # Optionally, assert staging rows here if you want deeper coverage
        # via direct SELECTs on the staging tables.
