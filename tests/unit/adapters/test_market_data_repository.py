from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.adapters.repositories.market_data_repository import (
    IntradayBarRow,
    MarketDataRepository,
)


@pytest.mark.anyio
async def test_upsert_and_get_latest():
    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5435/stacklion_test"
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        repo = MarketDataRepository(session)
        sid = uuid4()
        t0 = datetime(2025, 11, 10, 10, 0, tzinfo=UTC)
        n = await repo.upsert_intraday_bars(
            [
                IntradayBarRow(
                    symbol_id=sid,
                    ts=t0,
                    open="1.0",
                    high="2.0",
                    low="0.9",
                    close="1.5",
                    volume="100",
                ),
                IntradayBarRow(
                    symbol_id=sid,
                    ts=t0,
                    open="1.1",
                    high="2.2",
                    low="1.0",
                    close="1.6",
                    volume="120",
                ),  # update
            ]
        )
        assert n == 2
        latest = await repo.get_latest_intraday_bar(sid)
        assert latest is not None and str(latest.close) == "1.6"
