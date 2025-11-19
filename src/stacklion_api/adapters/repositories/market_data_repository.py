# src/stacklion_api/adapters/repositories/market_data_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Market data repository.

This repository provides persistence primitives for intraday bars backed by the
``md_intraday_bars_parent`` table.

Responsibilities
----------------
* Upsert (insert or update) intraday bars at the `(symbol_id, ts)` granularity.
* Fetch the latest intraday bar for a given symbol.
* Normalize numeric fields on read so downstream code sees canonical
  :class:`decimal.Decimal` values (no scale-padding artifacts).

Layer
-----
Adapters / repositories.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.infrastructure.database.models.md import IntradayBar

from .base_repository import BaseRepository


@dataclass(frozen=True)
class IntradayBarRow:
    """Write-side representation of an intraday bar.

    This row shape is used by ingest use cases to persist provider payloads
    into the canonical intraday storage.

    Attributes:
        symbol_id: Internal UUID of the symbol.
        ts: UTC timestamp of the bar (open time).
        open: Open price as a string to preserve provider precision.
        high: High price as a string.
        low: Low price as a string.
        close: Close price as a string.
        volume: Volume as a string.
        provider: Provider identifier (e.g. ``"marketstack"``).
    """

    symbol_id: UUID
    ts: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    provider: str = "marketstack"


class MarketDataRepository(BaseRepository[IntradayBar]):
    """Repository for intraday market data."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository.

        Args:
            session: Async SQLAlchemy session bound to the target database.
        """
        super().__init__(session)

    async def upsert_intraday_bars(self, rows: Sequence[IntradayBarRow]) -> int:
        """Insert or update a batch of intraday bars.

        For each row, performs an ``INSERT ... ON CONFLICT`` keyed by
        ``(symbol_id, ts)`` and updates all numeric fields plus ``provider``
        on conflict.

        Notes:
            The input batch is de-duplicated by ``(symbol_id, ts)`` to avoid
            PostgreSQL's ``ON CONFLICT DO UPDATE command cannot affect row a
            second time`` error when multiple rows share the same key in a
            single statement. The last occurrence wins.

        Args:
            rows: Sequence of :class:`IntradayBarRow` instances to persist.

        Returns:
            Number of rows processed (inserted or updated). This counts the
            input rows, not the number of distinct keys.
        """
        if not rows:
            return 0

        # Deduplicate by (symbol_id, ts): last write wins.
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

        # Use PostgreSQL-specific upsert for efficiency and atomicity.
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
        # Caller is responsible for committing; we only return the processed count.
        return len(rows)

    async def get_latest_intraday_bar(self, symbol_id: UUID) -> IntradayBar | None:
        """Return the latest intraday bar for a symbol.

        The "latest" bar is the one with the greatest ``ts`` for the given
        ``symbol_id``. Ordering is deterministic: ``ts`` descending and then
        ``symbol_id`` ascending with NULLS LAST on ``ts``. Numeric fields are
        normalized to canonical :class:`decimal.Decimal` instances so their
        string representation does not include provider-specific scale padding
        (e.g. ``"1.60000000"`` → ``"1.6"``).

        Args:
            symbol_id: Internal UUID of the symbol.

        Returns:
            The latest :class:`IntradayBar` instance, or ``None`` if no bars
            exist for the symbol.
        """
        stmt = select(IntradayBar).where(IntradayBar.symbol_id == symbol_id)
        stmt = self.order_by_latest(stmt, IntradayBar.ts, IntradayBar.symbol_id).limit(1)

        latest = await self.fetch_optional(stmt)
        if latest is None:
            return None

        self._normalize_bar_decimals(latest)
        return latest

    @staticmethod
    def _normalize_bar_decimals(bar: IntradayBar) -> None:
        """Normalize Decimal fields on an :class:`IntradayBar` instance.

        This mutates the ORM instance in-place, stripping trailing zeros from
        numeric fields so that ``str(bar.close)`` matches canonical expectations
        in tests and API contracts.

        Args:
            bar: ORM instance to normalize.
        """

        def _norm(value: Any) -> Any:
            if isinstance(value, Decimal):
                # normalize() removes trailing zeros and adjusts exponent
                # e.g. Decimal('1.60000000') → Decimal('1.6')
                return value.normalize()
            return value

        for attr in ("open", "high", "low", "close", "volume"):
            current = getattr(bar, attr, None)
            normalized = _norm(current)
            if normalized is not current:
                setattr(bar, attr, normalized)
