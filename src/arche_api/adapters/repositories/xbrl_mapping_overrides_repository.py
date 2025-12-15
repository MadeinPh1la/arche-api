# src/arche_api/adapters/repositories/xbrl_mapping_overrides_repository.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""SQLAlchemy implementation of the XBRL mapping overrides repository.

Purpose:
    Provide a concrete repository for loading XBRL mapping override rules from
    the ref.edgar_xbrl_mapping_overrides table into domain-level
    MappingOverrideRule instances.

Layer:
    adapters/repositories

Design:
    - Async SQLAlchemy session (AsyncSession or compatible).
    - No business logic: purely persistence and mapping.
    - Returns domain MappingOverrideRule objects for use with the
      XBRLMappingOverrideEngine in the domain layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from arche_api.adapters.repositories.base_repository import BaseRepository
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository as XBRLMappingOverridesRepositoryPort,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)
from arche_api.infrastructure.database.models.ref import EdgarXBRLMappingOverride


class _AsyncSessionLike(Protocol):
    """Minimal async session protocol used by this repository.

    This keeps the repository testable with dummy sessions while remaining
    compatible with SQLAlchemy's AsyncSession.
    """

    async def execute(self, statement: Select[Any], /, *args: Any, **kwargs: Any) -> Any:
        """Execute a SQLAlchemy statement and return a result."""
        ...


TSession = TypeVar("TSession", bound=_AsyncSessionLike)


class SqlAlchemyXBRLMappingOverridesRepository(
    BaseRepository[AsyncSession],
    XBRLMappingOverridesRepositoryPort,
):
    """SQLAlchemy-backed implementation of the XBRL mapping overrides repository."""

    def __init__(self, session: TSession) -> None:
        """Initialize the repository with a session-like object.

        Args:
            session:
                Async SQLAlchemy session or compatible object exposing an
                ``execute`` coroutine method.
        """
        # At runtime this can be any _AsyncSessionLike (dummy or real).
        # For mypy, we cast to AsyncSession to satisfy BaseRepository.
        super().__init__(cast(AsyncSession, session))

    async def list_all_rules(self) -> Sequence[MappingOverrideRule]:
        """Return all configured override rules."""
        stmt = select(EdgarXBRLMappingOverride)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    async def list_rules_for_concept(
        self,
        concept: str,
        taxonomy: str | None = None,
    ) -> Sequence[MappingOverrideRule]:
        """Return override rules targeting a specific XBRL concept.

        Args:
            concept:
                XBRL concept QName (e.g., "us-gaap:Revenues") for which rules
                should be retrieved.
            taxonomy:
                Optional taxonomy identifier (e.g., "US_GAAP_2024"). When
                provided, both taxonomy-specific rules and taxonomy-agnostic
                rules (source_taxonomy is NULL) are returned.
        """
        stmt = select(EdgarXBRLMappingOverride).where(
            EdgarXBRLMappingOverride.source_concept == concept,
        )

        if taxonomy is not None:
            # Include both taxonomy-specific and taxonomy-agnostic rules.
            stmt = stmt.where(
                (EdgarXBRLMappingOverride.source_taxonomy == taxonomy)
                | EdgarXBRLMappingOverride.source_taxonomy.is_(None)
            )

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: Any) -> MappingOverrideRule:
        """Map a persistence model or domain object to a MappingOverrideRule.

        Behavior:
            - If ``row`` is already a MappingOverrideRule, return it as-is.
            - Otherwise, treat it as an EdgarXBRLMappingOverride ORM row and
              construct a corresponding MappingOverrideRule.
        """
        # Tests sometimes feed a MappingOverrideRule directly via dummy sessions.
        if isinstance(row, MappingOverrideRule):
            return row

        # ORM path: EdgarXBRLMappingOverride row.

        # scope is stored as a string name (e.g., "GLOBAL") or an OverrideScope.
        raw_scope = row.scope
        scope = raw_scope if isinstance(raw_scope, OverrideScope) else OverrideScope[str(raw_scope)]

        # target_metric is stored as the CanonicalStatementMetric enum name, or NULL.
        raw_target_metric = getattr(row, "target_metric", None)
        if isinstance(raw_target_metric, CanonicalStatementMetric):
            target_metric: CanonicalStatementMetric | None = raw_target_metric
        elif raw_target_metric is None:
            target_metric = None
        else:
            target_metric = CanonicalStatementMetric[str(raw_target_metric)]

        return MappingOverrideRule(
            # Use the ORM primary key as the stable rule identifier.
            rule_id=str(row.id),
            scope=scope,
            source_concept=row.source_concept,
            source_taxonomy=row.source_taxonomy,
            match_cik=row.match_cik,
            match_industry_code=row.match_industry_code,
            match_analyst_id=row.match_analyst_id,
            match_dimensions=row.match_dimensions or {},
            target_metric=target_metric,
            is_suppression=bool(row.is_suppression),
            priority=int(row.priority),
        )


__all__ = ["SqlAlchemyXBRLMappingOverridesRepository"]
