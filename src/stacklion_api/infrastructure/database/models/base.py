"""
Declarative Base and canonical persistence mixins for Stacklion.

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

Caveats:
    * These mixins target PostgreSQL (TIMESTAMPTZ, JSONB). If you later add
      cross-database support, revisit server defaults and JSON types.
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

#: Default database schema for all tables (configurable via env).
DEFAULT_DB_SCHEMA: str | None = os.getenv("DB_SCHEMA", "public") or None

#: Deterministic naming conventions for Alembic-friendly diffs.
#: Ref: https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTIONS: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Central metadata with naming conventions applied.
metadata = MetaData(naming_convention=NAMING_CONVENTIONS)

#: Server-side default timestamp in **UTC** (PostgreSQL).
#: If you need cross-DB, consider `func.now()` and normalize in the app layer.
UTC_NOW_SQL = text("timezone('utc', now())")


# ======================================================================================
# Base
# ======================================================================================


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy Declarative Base.

    Attributes:
        metadata: Shared `MetaData` object with naming conventions.
    """

    metadata = metadata

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N802
        """Infer a snake_case table name from a PascalCase class name.

        Returns:
            The snake_case table name.

        Example:
            TradeOrder -> trade_order
        """
        name = cls.__name__
        name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
        name = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", name)
        return name.replace("__", "_").lower()

    @declared_attr.directive
    def __table_args__(cls) -> tuple[dict[str, Any]]:  # noqa: N802
        """Apply default schema uniformly (unless a subclass overrides).

        Returns:
            A single-element tuple with kwargs for Table construction.
        """
        return ({"schema": DEFAULT_DB_SCHEMA} if DEFAULT_DB_SCHEMA else {},)


# ======================================================================================
# Mixins (compose as needed in concrete models)
# ======================================================================================


class IdentityMixin:
    """Mixin providing a UUIDv4 primary key.

    Fields:
        id (UUID): Primary key generated application-side (uuid4).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        doc="Primary key (UUIDv4).",
    )


class TimestampMixin:
    """Mixin adding immutable `created_at` and mutable `updated_at` in UTC.

    Behavior:
        * Defaults are server-generated in DB (UTC).
        * `updated_at` refreshes server-side on UPDATE when the row changes.

    Fields:
        created_at (datetime): Creation timestamp (UTC, tz-aware).
        updated_at (datetime): Last modification timestamp (UTC, tz-aware).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=UTC_NOW_SQL,
        doc="Row creation timestamp (UTC).",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=UTC_NOW_SQL,
        onupdate=func.now(),
        doc="Row update timestamp (UTC).",
    )


class OptimisticLockingMixin:
    """Mixin enabling optimistic concurrency via a `version` column.

    Behavior:
        * `version` starts at 1 (server default) and is incremented by SQLAlchemy
          on UPDATE when the row changes.
        * SQLAlchemy compares previous value to prevent lost updates.

    Fields:
        version (int): Monotonically increasing version for OCC.

    Usage:
        class MyModel(IdentityMixin, OptimisticLockingMixin, Base): ...
    """

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        doc="Optimistic concurrency token (monotonic, starts at 1).",
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N802
        """Wire SQLAlchemy's versioning support to this column.

        Returns:
            Mapper configuration enabling SQLAlchemy's integer versioning.
        """
        return {
            "version_id_col": cls.version,
            "version_id_generator": False,  # SQLAlchemy increments integer automatically.
        }


class SoftDeleteMixin:
    """Mixin providing soft-delete semantics (nullable `deleted_at` in UTC).

    Behavior:
        * Soft-deleted rows retain data but are considered inactive.
        * Repositories should filter out rows where `deleted_at IS NOT NULL`.

    Fields:
        deleted_at (datetime | None): Deletion timestamp (UTC), null if active.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Soft-deletion timestamp (UTC). Null means not deleted.",
    )

    def mark_deleted(self) -> None:
        """Mark the row as soft-deleted with a UTC timestamp."""
        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        """Restore a soft-deleted row (clear deletion timestamp)."""
        self.deleted_at = None


class AuditActorMixin:
    """Provider-aware actor tracing for create/update operations.

    This is vendor-neutral and compatible with Clerk (auth) and Paddle (billing).

    Fields:
        created_by_provider (str | None): Origin of creator, e.g., "clerk", "api_key", "system", "paddle_webhook".
        created_by_id (str | None): External subject identifier (e.g., Clerk user ID, service account id).
        updated_by_provider (str | None): Origin of updater.
        updated_by_id (str | None): External subject identifier of updater.
        actor_context (dict | None): Opaque JSON for request metadata (e.g., ip, ua, key_id, webhook_id).

    Notes:
        * Keep IDs as text for flexibility—Clerk/Paddle identifiers are strings.
        * Avoid PII; store only stable technical identifiers (subject IDs).
    """

    created_by_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_by_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


# ======================================================================================
# Convenience utilities (persistence-safe)
# ======================================================================================


class ReprMixin:
    """Safe, concise `__repr__` including identity and key fields."""

    __repr_attrs__: tuple[str, ...] = ("id", "version", "created_at", "updated_at")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        """Return a compact representation including select attributes.

        Returns:
            String representation including a small set of attributes.
        """
        cls = self.__class__.__name__
        parts: list[str] = []
        for attr in self.__repr_attrs__:
            if hasattr(self, attr):
                try:
                    parts.append(f"{attr}={getattr(self, attr)!r}")
                except Exception:
                    parts.append(f"{attr}=<error>")
        return f"{cls}({', '.join(parts)})"


class SerializationMixin:
    """Shallow serialization helpers (for diagnostics/tests; not for API DTOs).

    These helpers intentionally avoid deep graph traversal and business mapping.
    Use adapters/mappers for API contracts instead.
    """

    def to_dict(self, *, exclude: Iterable[str] | None = None) -> dict[str, Any]:
        """Serialize mapped column attributes to a dict (shallow).

        Args:
            exclude: Optional iterable of attribute names to skip.

        Returns:
            A dictionary of public column values (columns only, no relationships).
        """
        from sqlalchemy import inspect as sa_inspect  # local import to avoid global overhead

        insp = sa_inspect(self)
        mapper = getattr(insp, "mapper", None)
        if mapper is None:
            cls = self.__class__.__name__
            raise RuntimeError(f"SQLAlchemy mapper is not initialized for instance of {cls}")

        excl = set(exclude or ())
        data: dict[str, Any] = {}
        for col in mapper.columns:
            name = col.key
            if name in excl:
                continue
            try:
                data[name] = getattr(self, name)
            except Exception:
                data[name] = None
        return data


# ======================================================================================
# Canonical base entity for persistence layer
# ======================================================================================


class BaseEntity(
    IdentityMixin,
    TimestampMixin,
    OptimisticLockingMixin,
    SoftDeleteMixin,
    AuditActorMixin,
    ReprMixin,
    SerializationMixin,
    Base,
):
    """Canonical persistence base for Stacklion models.

    Inherit this for most tables. If a table does not need some concerns
    (e.g., no soft-delete), compose only the required mixins.

    Example:
        class Security(BaseEntity):
            symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    """

    # Composition only; no additional columns.
    pass
