# src/stacklion_api/adapters/repositories/market_data_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Market data repository.

This repository provides persistence primitives for intraday bars backed by the
``md_intraday_bars_parent`` table.

Responsibilities
----------------
* Upsert (insert or update) intraday bars at the ``(symbol_id, ts)`` granularity.
* Fetch the latest intraday bar for a given symbol.
* Normalize numeric fields on read so downstream code sees canonical
  :class:`decimal.Decimal` values (no scale-padding artifacts).

Layer
-----
Adapters / repositories.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.infrastructure.database.models.md import IntradayBar
from stacklion_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


@dataclass(frozen=True)
class IntradayBarRow:
    """Write-side representation of an intraday bar."""

    symbol_id: UUID
    ts: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    provider: str = "marketstack"


class MarketDataRepository:
    """Repository for intraday market data."""

    _MODEL_NAME = "md_intraday_bars"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --------------------------------------------------------------------------
    # UPSERT
    # --------------------------------------------------------------------------

    async def upsert_intraday_bars(self, rows: Sequence[IntradayBarRow]) -> int:
        if not rows:
            return 0

        hist = get_db_operation_duration_seconds()
        err_counter = get_db_errors_total()

        start = time.perf_counter()
        outcome = "success"

        try:
            # Dedup last-write-wins
            dedup: dict[tuple[UUID, datetime], IntradayBarRow] = {}
            for r in rows:
                dedup[(r.symbol_id, r.ts)] = r

            payload = [
                {
                    "symbol_id": r.symbol_id,
                    "ts": r.ts,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "provider": r.provider,
                }
                for r in dedup.values()
            ]

            stmt = pg_insert(IntradayBar).values(payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=[IntradayBar.symbol_id, IntradayBar.ts],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "provider": stmt.excluded.provider,
                },
            )

            await self._session.execute(stmt)
            return len(rows)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"

            # Metrics must not affect correctness
            with suppress(Exception):
                err_counter.labels(
                    operation="upsert_intraday_bars",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()

            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                hist.labels(
                    operation="upsert_intraday_bars",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # --------------------------------------------------------------------------
    # GET LATEST
    # --------------------------------------------------------------------------

    async def get_latest_intraday_bar(self, symbol_id: UUID) -> IntradayBar | None:
        hist = get_db_operation_duration_seconds()
        err_counter = get_db_errors_total()

        start = time.perf_counter()
        outcome = "success"

        try:
            stmt = (
                select(IntradayBar)
                .where(IntradayBar.symbol_id == symbol_id)
                .order_by(IntradayBar.ts.desc())
                .limit(1)
            )

            latest = await self._session.scalar(stmt)
            if latest is None:
                return None

            self._normalize_bar_decimals(latest)
            return latest

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                err_counter.labels(
                    operation="get_latest_intraday_bar",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                hist.labels(
                    operation="get_latest_intraday_bar",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # --------------------------------------------------------------------------
    # Decimal normalization
    # --------------------------------------------------------------------------

    @staticmethod
    def _normalize_bar_decimals(bar: IntradayBar) -> None:
        """Normalize Decimal fields on the ORM instance."""

        def _norm(v: Any) -> Any:
            if isinstance(v, Decimal):
                return v.normalize()
            return v

        for field in ("open", "high", "low", "close", "volume"):
            val = getattr(bar, field, None)
            new = _norm(val)
            if new is not val:
                setattr(bar, field, new)
