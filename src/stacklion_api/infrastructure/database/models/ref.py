# src/stacklion_api/infrastructure/database/models/ref.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Reference data models: exchanges, companies, symbols."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from stacklion_api.infrastructure.database.models.base import Base


class Exchange(Base):
    """Exchange (MIC) registry."""

    __tablename__ = "exchanges"
    __table_args__ = ({"schema": "ref"},)

    mic: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2))
    timezone: Mapped[str] = mapped_column(String(64))


class Company(Base):
    """Issuer/company record (optional CIK)."""

    __tablename__ = "companies"
    __table_args__ = ({"schema": "ref"},)

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    cik: Mapped[str | None] = mapped_column(String(10), unique=True)


class Symbol(Base):
    """Listed symbol mapping ticker↔MIC with primary flag and life dates."""

    __tablename__ = "symbols"
    __table_args__ = ({"schema": "ref"},)

    symbol_id: Mapped[UUID] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    mic: Mapped[str] = mapped_column(String(10), ForeignKey("ref.exchanges.mic"))
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("ref.companies.company_id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    listed_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    listed_to: Mapped[date | None] = mapped_column(Date, nullable=True)
