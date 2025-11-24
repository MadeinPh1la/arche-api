# src/stacklion_api/adapters/uow/sqlalchemy_uow.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
SQLAlchemy-backed Unit of Work implementation.

Purpose:
    Provide a concrete implementation of the application-layer UnitOfWork
    protocol using SQLAlchemy's AsyncSession. This UoW coordinates one or
    more repository instances within a single transactional scope.

Layer:
    adapters/uow
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stacklion_api.adapters.repositories.edgar_filings_repository import (
    EdgarFilingsRepository,
)
from stacklion_api.adapters.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.application.uow import UnitOfWork


class SqlAlchemyUnitOfWork(UnitOfWork):
    """SQLAlchemy-based UnitOfWork implementation."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repo_factories: Mapping[type[Any], Callable[[AsyncSession], Any]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

        default_factories: dict[type[Any], Callable[[AsyncSession], Any]] = {
            EdgarFilingsRepository: lambda s: EdgarFilingsRepository(session=s),
            EdgarStatementsRepository: lambda s: EdgarStatementsRepository(session=s),
        }

        self._repo_factories: dict[type[Any], Callable[[AsyncSession], Any]] = {
            **default_factories,
            **(dict(repo_factories) if repo_factories is not None else {}),
        }

        self._repos: dict[type[Any], Any] = {}
        self._committed = False
        self._rolled_back = False

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("UnitOfWork is already active; nested usage is not supported.")

        self._session = self._session_factory()
        self._committed = False
        self._rolled_back = False
        self._repos.clear()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        try:
            if exc_type is not None and not self._rolled_back:
                await self.rollback()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None
            self._repos.clear()
        return None

    # ------------------------------------------------------------------
    # Transaction control
    # ------------------------------------------------------------------

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Cannot commit: UnitOfWork has no active session.")

        if self._committed or self._rolled_back:
            return

        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is None:
            return

        if self._rolled_back or self._committed:
            return

        await self._session.rollback()
        self._rolled_back = True

    # ------------------------------------------------------------------
    # Repository resolution
    # ------------------------------------------------------------------

    def get_repository(self, repo_type: type[Any]) -> Any:
        if self._session is None:
            raise RuntimeError(
                "get_repository() called outside of an active UnitOfWork scope. "
                "Use 'async with uow:' before requesting repositories.",
            )

        if repo_type in self._repos:
            return self._repos[repo_type]

        try:
            factory = self._repo_factories[repo_type]
        except KeyError as exc:
            raise KeyError(
                f"No repository factory registered for type {repo_type!r}.",
            ) from exc

        repo = factory(self._session)
        self._repos[repo_type] = repo
        return repo
