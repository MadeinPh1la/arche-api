# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market data ORM models for partitioned bars.

These ORM classes map to the partition parents created by migrations. Actual
monthly partitions inherit structure automatically at the database level.

All times are UTC. Prices use NUMERIC(20,8); volume uses NUMERIC(38,0).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Numeric, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Local declarative base for market data models."""

    pass


class IntradayBar(Base):
    """Intraday OHLCV bar (partition parent)."""

    __tablename__ = "md_intraday_bars_parent"
    __table_args__ = {"schema": None}

    symbol_id: Mapped[UUID] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[str] = mapped_column(Numeric(38, 0), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'marketstack'")
    )


class EodBar(Base):
    """End-of-day OHLCV bar (partition parent)."""

    __tablename__ = "md_eod_bars_parent"
    __table_args__ = {"schema": None}

    symbol_id: Mapped[UUID] = mapped_column(primary_key=True)
    d: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[str] = mapped_column(Numeric(20, 8), nullable=False)
    adj_close: Mapped[str | None] = mapped_column(Numeric(20, 8), nullable=True)
    volume: Mapped[str] = mapped_column(Numeric(38, 0), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'marketstack'")
    )
