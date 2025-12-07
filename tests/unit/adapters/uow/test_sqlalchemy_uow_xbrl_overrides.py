# tests/unit/adapters/uow/test_sqlalchemy_uow_xbrl_overrides.py
from __future__ import annotations

import pytest

from stacklion_api.adapters.repositories.xbrl_mapping_overrides_repository import (
    SqlAlchemyXBRLMappingOverridesRepository,
)
from stacklion_api.adapters.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
from stacklion_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository,
)


class _FakeAsyncSession:
    """Minimal async-session stand-in for UoW wiring tests.

    This fake implements only the methods that SqlAlchemyUnitOfWork expects
    on its session: commit, rollback, and close. No real database or
    SQLAlchemy engine is involved.
    """

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        """Mark the session as committed."""
        self.committed = True

    async def rollback(self) -> None:
        """Mark the session as rolled back."""
        self.rolled_back = True

    async def close(self) -> None:
        """Mark the session as closed."""
        self.closed = True


def _fake_session_factory() -> _FakeAsyncSession:
    """Session factory compatible with SqlAlchemyUnitOfWork.

    Returns a new _FakeAsyncSession instance on each call, mirroring the
    behavior of an async_sessionmaker without touching SQLAlchemy.
    """
    return _FakeAsyncSession()


@pytest.mark.asyncio
async def test_uow_resolves_xbrl_mapping_overrides_repository() -> None:
    """SqlAlchemyUnitOfWork should resolve the XBRL mapping overrides repository.

    This is a pure wiring test:

    * Uses a fake async session factory (no engine, no DB).
    * Verifies that SqlAlchemyUnitOfWork can return an implementation of
      the XBRLMappingOverridesRepository interface when requested.
    """
    uow = SqlAlchemyUnitOfWork(session_factory=_fake_session_factory)

    async with uow as tx:
        repo = tx.get_repository(XBRLMappingOverridesRepository)

        # We only care that the UoW wiring returns *some* implementation
        # of the XBRLMappingOverridesRepository interface.
        assert isinstance(repo, SqlAlchemyXBRLMappingOverridesRepository)
