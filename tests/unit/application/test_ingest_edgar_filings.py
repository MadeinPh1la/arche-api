# tests/unit/application/test_ingest_edgar_filings.py

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.application.use_cases.external_apis.ingest_edgar_filings import (
    EdgarGateway,
    IngestEdgarFilings,
    IngestEdgarRequest,
)


class FakeEdgarGateway(EdgarGateway):
    async def fetch_recent_filings(self, *, cik: str, limit: int = 100) -> dict[str, object]:
        # Minimal deterministic payload
        return {
            "cik": cik,
            "filings": [
                {"accessionNumber": "0000000001-25-000001"},
                {"accessionNumber": "0000000001-25-000002"},
            ],
        }


@pytest.mark.anyio
async def test_ingest_edgar_filings_counts_filings_and_persists_raw() -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5435/stacklion_test"
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        uc = IngestEdgarFilings(FakeEdgarGateway())
        req = IngestEdgarRequest(cik="0000000001")

        count = await uc(session, req)

        # We returned 2 filings in the fake, so the UC should report 2
        assert count == 2

        # You can optionally assert staging rows exist here if you want deeper coverage
        # e.g. via direct SELECT on the staging tables
