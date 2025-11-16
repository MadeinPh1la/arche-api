# tests/unit/application/test_ingest_marketstack_intraday.py
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.application.interfaces.market_data_gateway import MarketDataGateway
from stacklion_api.application.use_cases.external_apis.ingest_marketstack_intraday import (
    IngestIntradayRequest,
    IngestMarketstackIntradayBars,
)

# Use CI-friendly DB URL by default, overridable via env for local dev.
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
)


class FakeGateway(MarketDataGateway):
    async def fetch_intraday_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        page_size: int,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Produce a single deterministic intraday bar."""
        ts = start.replace(tzinfo=UTC, microsecond=0).isoformat().replace("+00:00", "Z")
        bars = [
            {
                "ts": ts,
                "open": "1.0",
                "high": "2.0",
                "low": "0.9",
                "close": "1.5",
                "volume": "100",
            }
        ]
        meta: dict[str, Any] = {
            "etag": "test-etag",
            "count": len(bars),
        }
        return bars, meta


@pytest.mark.anyio
async def test_ingest_intraday_basic() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        uc = IngestMarketstackIntradayBars(FakeGateway())

        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC)

        n = await uc(
            session,
            IngestIntradayRequest(
                symbol_id=uuid4(),
                ticker="MSFT",
                window_from=start,
                window_to=end,
                interval="1min",
            ),
        )

        # We expect exactly one upserted bar from the FakeGateway
        assert n == 1
