# Copyright (c)
# SPDX-License-Identifier: MIT
"""Replay raw staging payloads into market-data tables deterministically.

Reads `staging.raw_payloads` for a given (source, endpoint) and optional
symbol/time filters, normalizes rows, and upserts into partitioned tables.
This is safe to run repeatedly.

Layer:
    application/use_cases/maintenance
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ReplayRequest:
    """Parameters for staging→md replay."""

    source: str
    endpoint: str
    symbol_id: UUID
    ticker: str
    window_from: datetime | None = None
    window_to: datetime | None = None


class ReplayStagingToMd:
    """Deterministic replay from staging.raw_payloads into md.* tables."""

    async def __call__(self, session: AsyncSession, req: ReplayRequest) -> int:
        """Execute replay for the requested slice.

        Args:
            session: Database session used for reading staging and writing md.
            req: Replay parameters including source, endpoint, and filters.

        Returns:
            Total number of upserted market-data rows.
        """
        staging_models = import_module("arche_api.infrastructure.database.models.staging")
        RawPayload = staging_models.RawPayload

        md_module = import_module("arche_api.adapters.repositories.market_data_repository")
        MarketDataRepository = md_module.MarketDataRepository
        IntradayBarRow = md_module.IntradayBarRow

        q = select(RawPayload).where(
            RawPayload.source == req.source,
            RawPayload.endpoint == req.endpoint,
            RawPayload.symbol_or_cik == req.ticker,
        )
        if req.window_from:
            q = q.where(RawPayload.window_from >= req.window_from)
        if req.window_to:
            q = q.where(RawPayload.window_to <= req.window_to)

        res = await session.execute(q.order_by(RawPayload.received_at.asc()))
        payloads: Iterable[Any] = res.scalars()

        md_repo = MarketDataRepository(session)
        total = 0
        for p in payloads:
            data = (p.payload or {}).get("data") or []
            rows = [
                IntradayBarRow(
                    symbol_id=req.symbol_id,
                    ts=datetime.fromisoformat(x["ts"].replace("Z", "+00:00")).astimezone(UTC),
                    open=x["open"],
                    high=x["high"],
                    low=x["low"],
                    close=x["close"],
                    volume=x["volume"],
                )
                for x in data
            ]
            total += int(await md_repo.upsert_intraday_bars(rows))

        await session.commit()
        return total
