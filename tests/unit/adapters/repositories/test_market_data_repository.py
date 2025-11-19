# tests/unit/adapters/test_market_data_repository.py
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.adapters.repositories.market_data_repository import (
    IntradayBarRow,
    MarketDataRepository,
)

# Use the same database URL as CI by default, but allow overrides via env.
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
)


@pytest.mark.anyio
async def test_upsert_and_get_latest() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
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
        assert latest is not None
        assert str(latest.close) == "1.6"


@pytest.mark.anyio
async def test_get_latest_is_deterministic_with_multiple_rows() -> None:
    """Repository must deterministically surface the max-ts bar."""
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        repo = MarketDataRepository(session)
        sid = uuid4()
        base_ts = datetime(2025, 11, 10, 10, 0, tzinfo=UTC)

        # Insert bars in non-sorted order to prove ORDER BY drives semantics.
        rows = [
            IntradayBarRow(
                symbol_id=sid,
                ts=base_ts + timedelta(minutes=1),
                open="1.1",
                high="2.1",
                low="1.0",
                close="1.6",
                volume="110",
            ),
            IntradayBarRow(
                symbol_id=sid,
                ts=base_ts,
                open="1.0",
                high="2.0",
                low="0.9",
                close="1.5",
                volume="100",
            ),
            IntradayBarRow(
                symbol_id=sid,
                ts=base_ts + timedelta(minutes=2),
                open="1.2",
                high="2.2",
                low="1.1",
                close="1.7",
                volume="120",
            ),
        ]

        await repo.upsert_intraday_bars(rows)
        latest = await repo.get_latest_intraday_bar(sid)

        assert latest is not None
        # Max timestamp row should always win regardless of insert order.
        assert latest.ts == base_ts + timedelta(minutes=2)
        assert str(latest.close) == "1.7"
