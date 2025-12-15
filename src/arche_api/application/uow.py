# src/arche_api/application/uow.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Unit of Work (Application Layer).

Purpose:
    Define the abstract Unit-of-Work boundary used by application-layer
    use cases to coordinate transactional work across one or more
    repositories.

    This module is intentionally infrastructure-agnostic:
        * No SQLAlchemy / DB / HTTP imports.
        * No concrete repository implementations.
        * Only Protocols and helper utilities for use cases.

    Concrete implementations (e.g., SQLAlchemy-backed UoW) live in the
    adapters/ layer and must satisfy this protocol.

Layer:
    application
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, Protocol, TypeVar, runtime_checkable

TResult = TypeVar("TResult")


@runtime_checkable
class UnitOfWork(Protocol, AbstractAsyncContextManager["UnitOfWork"]):
    """Abstract Unit-of-Work contract for application use cases."""

    async def __aenter__(self) -> UnitOfWork:
        """Enter the transactional scope and return the active UoW."""
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        """Exit the transactional scope."""
        raise NotImplementedError

    async def commit(self) -> None:
        """Commit all pending changes for this UnitOfWork."""
        raise NotImplementedError

    async def rollback(self) -> None:
        """Roll back any pending changes for this UnitOfWork."""
        raise NotImplementedError

    def get_repository(self, repo_type: type[Any]) -> Any:
        """Return a repository instance for the given key/type.

        Args:
            repo_type:
                Opaque key used to resolve a repository. In practice this is
                typically a concrete repository class or a protocol/interface
                type, but the UnitOfWork is free to interpret it as needed.
        """
        raise NotImplementedError


async def run_in_uow(  # noqa: UP047
    uow: UnitOfWork,
    fn: Callable[[UnitOfWork], Awaitable[TResult]],
) -> TResult:
    """Execute a coroutine against a UnitOfWork with commit/rollback semantics.

    The helper guarantees that:

        * On success: the transaction is committed.
        * On exception: the transaction is rolled back and the exception is
          re-raised.

    Args:
        uow: UnitOfWork instance providing transactional boundaries.
        fn: Callable that receives the active UnitOfWork and returns a result.

    Returns:
        TResult: The result of the callable.

    Raises:
        Exception: Any exception raised by ``fn`` is propagated after rollback.
    """
    async with uow as tx:
        try:
            result = await fn(tx)
        except Exception:
            await tx.rollback()
            raise
        else:
            await tx.commit()
            return result
