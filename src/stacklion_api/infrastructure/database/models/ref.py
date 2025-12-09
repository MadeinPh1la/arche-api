# src/stacklion_api/infrastructure/database/models/ref.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Reference data models: exchanges, companies, symbols, and mapping overrides."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from stacklion_api.infrastructure.database.models.base import (
    AuditActorMixin,
    Base,
    IdentityMixin,
    JSONBType,
    TimestampMixin,
)


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


class EdgarXBRLMappingOverride(IdentityMixin, TimestampMixin, AuditActorMixin, Base):
    """Ref-table backing XBRL mapping override rules.

    Schema:
        ref.edgar_xbrl_mapping_overrides

    Purpose:
        Persist override rules used by the domain-level XBRL mapping override
        engine. This table is treated as reference/configuration data and is
        typically managed out-of-band (admin tooling, migrations, or static
        bootstrap).

    Notes:
        - ``scope`` stores the OverrideScope enum name (e.g. "GLOBAL").
        - ``target_metric`` stores CanonicalStatementMetric.name when present.
        - ``match_dimensions`` is a JSONB object representing axis → member.
    """

    __tablename__ = "edgar_xbrl_mapping_overrides"
    __table_args__ = ({"schema": "ref"},)

    # IdentityMixin provides:
    #   id: UUID primary key

    scope: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    source_concept: Mapped[str] = mapped_column(String(256), nullable=False)
    source_taxonomy: Mapped[str | None] = mapped_column(String(64), nullable=True)

    match_cik: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    match_industry_code: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    match_analyst_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    match_dimensions: Mapped[dict[str, str]] = mapped_column(
        JSONBType,
        nullable=False,
        default=dict,
    )

    target_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_suppression: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EdgarXBRLMappingOverrideHistory(
    IdentityMixin,
    TimestampMixin,
    AuditActorMixin,
    Base,
):
    """Append-only history for XBRL mapping override rules.

    Schema:
        ref.edgar_xbrl_mapping_overrides_history

    Purpose:
        Capture immutable snapshots of override rules across their lifecycle,
        including creations, updates, and deprecations.

    Notes:
        - Each change to the primary override row creates a new history record.
        - The combination (override_id, version_sequence) is unique and
          determines ordering.
    """

    __tablename__ = "edgar_xbrl_mapping_overrides_history"
    __table_args__ = ({"schema": "ref"},)

    override_id: Mapped[UUID] = mapped_column(
        ForeignKey("ref.edgar_xbrl_mapping_overrides.id"),
        nullable=False,
        index=True,
    )

    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deprecation_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    source_concept: Mapped[str] = mapped_column(String(256), nullable=False)
    source_taxonomy: Mapped[str | None] = mapped_column(String(64), nullable=True)

    match_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    match_industry_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_analyst_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    match_dimensions: Mapped[dict[str, str]] = mapped_column(
        JSONBType,
        nullable=False,
        default=dict,
    )

    target_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_suppression: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
