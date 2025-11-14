# src/stacklion_api/infrastructure/database/maintenance/partitions.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Partition maintenance utilities for monthly partitions.

Creates forward monthly partitions for the intraday and EOD parent tables.

Layer:
    infrastructure/database/maintenance
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["create_forward_partitions"]


async def create_forward_partitions(session: AsyncSession, *, months: int) -> int:
    """Create monthly partitions for the next ``months`` months (including current).

    This function issues idempotent
    ``CREATE TABLE IF NOT EXISTS ... PARTITION OF ... FOR VALUES FROM ... TO ...``
    DDL for both intraday and EOD parent tables. It commits on success.

    Args:
        session: Async SQLAlchemy session.
        months: Number of forward months to pre-create (>= 1).

    Returns:
        int: Total number of partition tables created or ensured to exist.
    """
    if months < 1:
        return 0

    created = 0
    today = date.today()
    y, m = today.year, today.month

    for i in range(months):
        yy = y + ((m - 1 + i) // 12)
        mm = ((m - 1 + i) % 12) + 1

        start = f"{yy}-{mm:02d}-01"
        ey, em = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
        end = f"{ey}-{em:02d}-01"

        # Intraday partition
        await session.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS md.intraday_bars_{yy}_{mm:02d}
                PARTITION OF md_intraday_bars_parent
                FOR VALUES FROM ('{start}') TO ('{end}');
                """
            )
        )
        created += 1

        # EOD partition
        await session.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS md.eod_bars_{yy}_{mm:02d}
                PARTITION OF md_eod_bars_parent
                FOR VALUES FROM ('{start}') TO ('{end}');
                """
            )
        )
        created += 1

    await session.commit()
    return created
