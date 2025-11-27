"""Declarative Base and canonical persistence mixins for Stacklion.

This module defines:
    - A project-wide SQLAlchemy Declarative Base with deterministic naming
      conventions (for stable Alembic diffs).
    - Persistence mixins for identity (UUIDv4), audit timestamps (UTC),
      soft-delete, optimistic concurrency control, and provider-aware audit actor.
    - Lightweight utilities for safe repr and shallow serialization (no domain logic).

Design Goals:
    * Production correctness: UTC everywhere, safe defaults, minimal surprises.
    * Deterministic schema: Alembic-friendly naming conventions prevent churn.
    * Separation of concerns: Persistence-only; no domain/business behavior.
    * Extensibility: Mixins compose cleanly; projects can opt-in per model.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import MetaData, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime, Integer, String

try:  # pragma: no cover - avoid hard failure in tooling/migrations
    from stacklion_api.config.settings import get_settings
except Exception:  # pragma: no cover
    get_settings = None  # type: ignore[assignment]

__all__ = [
    "metadata",
    "Base",
    "BaseEntity",
    "IdentityMixin",
    "TimestampMixin",
    "OptimisticLockingMixin",
    "SoftDeleteMixin",
    "AuditActorMixin",
    "ReprMixin",
    "SerializationMixin",
]

# ======================================================================================
# Configuration
# ======================================================================================

#: Default database schema for all tables (configurable via Settings / env).
try:
    # Use canonical Settings when available.
    _settings = get_settings() if get_settings is not None else None
    DEFAULT_DB_SCHEMA: str | None = (
        _settings.db_schema if _settings else os.getenv("DB_SCHEMA", "public") or None
    )
except Exception:  # pragma: no cover - minimal fallback for edge tooling cases
    DEFAULT_DB_SCHEMA = os.getenv("DB_SCHEMA", "public") or None

#: Deterministic naming conventions for Alembic-friendly diffs.
#: Ref: https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTIONS: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTIONS)


class Base(DeclarativeBase):
    """Declarative Base for all ORM models.

    This base attaches the metadata with stable naming conventions and
    configures a default PostgreSQL schema via ``DEFAULT_DB_SCHEMA``.
    """

    metadata = metadata

    @declared_attr.directive
    def __table_args__(cls) -> tuple[dict[str, Any]] | tuple[()]:
        """Attach default schema when configured.

        Returns:
            tuple: Table arguments containing the schema mapping, if configured.
        """
        if DEFAULT_DB_SCHEMA:
            return ({"schema": DEFAULT_DB_SCHEMA},)
        return ()


class IdentityMixin:
    """Mixin providing a UUIDv4 primary key ``id`` column."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        unique=True,
    )


class TimestampMixin:
    """Mixin providing immutable ``created_at`` and mutable ``updated_at`` timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
        server_default=func.now(),
    )


class OptimisticLockingMixin:
    """Mixin providing an integer ``version`` column for optimistic locking."""

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class SoftDeleteMixin:
    """Mixin providing a nullable ``deleted_at`` timestamp for soft-deletes."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        """Return True if the row has been soft-deleted."""
        return self.deleted_at is not None

    def mark_deleted(self) -> None:
        """Mark the entity as deleted."""
        self.deleted_at = datetime.now(UTC)


class AuditActorMixin:
    """Mixin for tracking the actor responsible for changes."""

    created_by: Mapped[str | None] = mapped_column(
        String(length=255),
        nullable=True,
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(length=255),
        nullable=True,
    )

    def set_created_by(self, actor: str | None) -> None:
        """Set the creator actor identifier.

        Args:
            actor: Actor identifier (e.g., user id, service name).
        """
        self.created_by = actor

    def set_updated_by(self, actor: str | None) -> None:
        """Set the updater actor identifier.

        Args:
            actor: Actor identifier (e.g., user id, service name).
        """
        self.updated_by = actor


class ReprMixin:
    """Mixin providing a concise, field-based ``__repr__`` implementation."""

    def __repr__(self) -> str:
        """Return a short debug representation of the model.

        Returns:
            str: Representation including class name and key attributes.
        """
        cls = type(self)
        attrs = []
        for name in dir(self):
            if name.startswith("_"):
                continue
            if name in {"metadata", "registry"}:
                continue
            value = getattr(self, name, None)
            if callable(value):
                continue
            if isinstance(value, (str, int, float, bool, uuid.UUID)):
                attrs.append(f"{name}={value!r}")
        joined = ", ".join(sorted(attrs))
        return f"{cls.__name__}({joined})"


class SerializationMixin:
    """Mixin providing a shallow ``to_dict`` JSON-serializable representation."""

    def to_dict(self, *, include: Iterable[str] | None = None) -> dict[str, Any]:
        """Return a shallow dictionary representation of the model.

        Args:
            include: Optional iterable of attribute names to include. If omitted,
                a default heuristic is used (public, non-callable attributes).

        Returns:
            dict[str, Any]: Mapping of attribute names to simple values.
        """
        attrs: Iterable[str]
        if include is not None:
            attrs = include
        else:
            attrs = [
                name
                for name in dir(self)
                if not name.startswith("_")
                and name not in {"metadata", "registry"}
                and not callable(getattr(self, name, None))
            ]

        result: dict[str, Any] = {}
        for name in attrs:
            value = getattr(self, name, None)
            if isinstance(value, datetime):
                result[name] = value.astimezone(UTC).isoformat()
            elif isinstance(value, uuid.UUID):
                result[name] = str(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                result[name] = value
        return result


class BaseEntity(IdentityMixin, TimestampMixin, Base):
    """Concrete base class for most entities in the system."""

    __abstract__ = True

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp to now (UTC)."""
        self.updated_at = datetime.now(UTC)


# Example JSONB usage re-export (if you use JSONB in models)
JSONBType = JSONB


def normalize_identifier(name: str) -> str:
    """Normalize a Python identifier into a safe SQL identifier.

    Args:
        name: Input identifier.

    Returns:
        str: Normalized identifier.
    """
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", name)
    return safe.strip("_").lower()


def now_utc() -> datetime:
    """Return the current UTC time with timezone info."""
    return datetime.now(UTC)


def utc_now_sql() -> Any:
    """Return a SQLAlchemy expression for current UTC timestamp."""
    return text("TIMEZONE('utc', CURRENT_TIMESTAMP)")
