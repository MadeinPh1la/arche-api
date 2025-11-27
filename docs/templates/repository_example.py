# docs/templates/repository_example.py
"""Example repository (SQLAlchemy 2.0).

Purpose:
- Demonstrate deterministic querying, error translation, and transaction safety.

Layer: adapters

Notes:
- No HTTP or FastAPI imports. Returns domain or DTO types, not ORM models.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Boolean, Select, cast, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.exceptions import InfrastructureException
from stacklion_api.infrastructure.database.models.md import QuoteModel


class SQLAlchemyQuoteRepository:
    """Canonical repository for quote data.

    Args:
        session: Async SQLAlchemy session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_ticker(self, ticker: str) -> Sequence[Quote]:
        """Fetch all active quotes for a ticker in deterministic order.

        Args:
            ticker: Canonical ticker symbol.

        Returns:
            A sequence of Quote entities sorted by timestamp asc, id asc.

        Raises:
            InfrastructureException: If the underlying database operation fails.
        """
        stmt: Select[tuple[QuoteModel]] = (
            select(QuoteModel)
            .where(
                QuoteModel.ticker == ticker,
                cast(QuoteModel.is_active == True, Boolean),  # noqa: E712
            )
            .order_by(QuoteModel.ts.asc(), QuoteModel.id.asc())
        )

        try:
            result = await self._session.execute(stmt)
        except SQLAlchemyError as exc:  # pragma: no cover - error path
            raise InfrastructureException("database error while listing quotes") from exc

        rows = result.scalars().all()
        return tuple(
            Quote(
                id=row.id or UUID(int=0),
                ticker=row.ticker,
                ts=row.ts,
                price=row.price,
            )
            for row in rows
        )
