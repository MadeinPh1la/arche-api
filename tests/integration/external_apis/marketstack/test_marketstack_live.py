# tests/integration/external_apis/test_marketstack_live.py
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arche_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from arche_api.adapters.repositories.market_data_repository import (
    IntradayBarRow,
    MarketDataRepository,
)
from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
)
from arche_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


@pytest.mark.anyio
async def test_marketstack_live_ingest_smoke() -> None:
    api_key = os.getenv("MARKETSTACK_API_KEY")
    if not api_key:
        pytest.skip("MARKETSTACK_API_KEY not set – skipping live Marketstack test")

    db_url = os.getenv(
        "STACKLION_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5435/arche_test",
    )

    engine = create_async_engine(db_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        async with httpx.AsyncClient() as http_client:
            settings = MarketstackSettings(
                access_key=api_key,  # pydantic will coerce to SecretStr
            )
            gateway = MarketstackGateway(client=http_client, settings=settings)

            now = datetime.now(tz=UTC)
            start = now - timedelta(hours=1)

            try:
                records, meta = await gateway.fetch_intraday_bars(
                    symbol="AAPL",
                    start=start,
                    end=now,
                    interval="1min",
                )
            except (
                MarketDataBadRequest,
                MarketDataRateLimited,
                MarketDataQuotaExceeded,
                MarketDataUnavailable,
            ) as exc:
                # Provider/plan issue, not a wiring bug in our code.
                pytest.skip(f"Marketstack intraday not available for this key/plan: {exc!r}")

        if not records:
            pytest.skip("Marketstack returned no intraday bars (market closed or empty window)")

        repo = MarketDataRepository(session)
        sid = uuid4()

        rows: list[IntradayBarRow] = []
        for r in records:
            ts = datetime.fromisoformat(r.ts.replace("Z", "+00:00")).astimezone(UTC)
            rows.append(
                IntradayBarRow(
                    symbol_id=sid,
                    ts=ts,
                    open=r.open,
                    high=r.high,
                    low=r.low,
                    close=r.close,
                    volume=r.volume,
                    provider="marketstack",
                )
            )

        processed = await repo.upsert_intraday_bars(rows)
        await session.commit()

        assert processed == len(rows)

        latest = await repo.get_latest_intraday_bar(sid)
        assert latest is not None
        assert latest.close > 0
