# src/stacklion_api/adapters/dependencies/edgar_uow.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR UnitOfWork dependency wiring.

Purpose:
    Provide a concrete, SQLAlchemy-backed UnitOfWork instance for EDGAR
    application use cases, backed by the core async_sessionmaker.

Layer:
    adapters/dependencies
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stacklion_api.adapters.uow import SqlAlchemyUnitOfWork
from stacklion_api.infrastructure.database.session import get_sessionmaker


def get_edgar_uow() -> SqlAlchemyUnitOfWork:
    """Construct a UnitOfWork instance for EDGAR use cases.

    Behavior:
        - Obtains the global async_sessionmaker via `get_sessionmaker()`.
        - Returns a fresh SqlAlchemyUnitOfWork bound to that factory.
        - Each call returns a new UoW instance (one per use-case invocation).
    """
    session_factory: async_sessionmaker[AsyncSession] = get_sessionmaker()
    return SqlAlchemyUnitOfWork(session_factory=session_factory)
