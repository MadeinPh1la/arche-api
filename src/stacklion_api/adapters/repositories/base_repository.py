# src/stacklion_api/adapters/repositories/base_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""
BaseRepository: Rule-enforcing repository foundation for Stacklion.

Purpose:
    Shared mechanics for all repositories:
      * Deterministic ordering helpers (NULLS LAST + PK tie-breakers).
      * Safe fetch helpers (one, optional, all).
      * Boolean-cast helper for dialect-correct WHERE clauses.
      * UTC timestamp helpers for audit fields.

Layer: adapters / repositories

Notes:
    * No business logic, no domain decisions.
    * Repositories never commit; use cases own transactions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import Boolean as SABoolean
from sqlalchemy import Select, cast, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

TModel = TypeVar("TModel")


class BaseRepository(Generic[TModel]):  # noqa: UP046
    """Abstract base class for all repositories."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the target database.
        """
        self._session: AsyncSession = session

    # ------------------------------------------------------------------
    # Timestamp / audit utilities
    # ------------------------------------------------------------------

    @staticmethod
    def utc_now() -> datetime:
        """Return current UTC time with timezone info."""
        return datetime.now(UTC)

    @staticmethod
    def as_true(expr: ColumnElement[Any]) -> ColumnElement[bool]:
        """Cast an expression to Boolean for dialect-safe WHERE clauses.

        This is useful when a comparison or function may not be statically
        typed as Boolean across drivers but is semantically boolean.
        """
        # Use a Boolean() instance to satisfy SQLAlchemy's type expectations.
        return cast(expr, SABoolean())

    # ------------------------------------------------------------------
    # Deterministic ordering utilities
    # ------------------------------------------------------------------

    @staticmethod
    def order_by_latest(
        stmt: Select[Any],
        timestamp_col: Any,
        pk_col: Any,
    ) -> Select[Any]:
        """Apply deterministic latest-first ordering.

        The resulting query orders by:

            timestamp DESC NULLS LAST, pk ASC
        """
        return stmt.order_by(
            nulls_last(timestamp_col.desc()),
            pk_col.asc(),
        )

    @staticmethod
    def order_by_created(
        stmt: Select[Any],
        created_col: Any,
        pk_col: Any,
    ) -> Select[Any]:
        """Apply deterministic ordering by creation time.

        The resulting query orders by:

            created_at DESC NULLS LAST, pk ASC
        """
        return stmt.order_by(
            nulls_last(created_col.desc()),
            pk_col.asc(),
        )

    @staticmethod
    def order_by_pk(
        stmt: Select[Any],
        pk_col: Any,
        *,
        ascending: bool = True,
    ) -> Select[Any]:
        """Apply ordering by primary key only.

        This is a pure tie-break ordering and should usually be composed with
        a more semantic primary sort key.
        """
        return stmt.order_by(pk_col.asc() if ascending else pk_col.desc())

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    async def fetch_one(self, stmt: Select[Any]) -> TModel:
        """Execute a statement and return a single row or raise.

        This uses the scalar result set; callers should prefer DTO mapping at
        the application layer instead of returning ORM models directly.
        """
        res = await self._session.execute(stmt)
        return res.scalars().one()

    async def fetch_optional(self, stmt: Select[Any]) -> TModel | None:
        """Execute a statement and return zero or one row."""
        res = await self._session.execute(stmt)
        return res.scalars().first()

    async def fetch_all(self, stmt: Select[Any]) -> list[TModel]:
        """Execute a statement and return all rows as a list."""
        res = await self._session.execute(stmt)
        return list(res.scalars().all())
