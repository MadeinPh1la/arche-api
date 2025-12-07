# tests/unit/adapters/repositories/test_xbrl_mapping_overrides_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Adapter tests for the XBRL mapping overrides repository.

Covers:
    - Construction with a generic SQLAlchemy-like session.
    - Basic query wiring shape (no real DB required).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from stacklion_api.adapters.repositories.xbrl_mapping_overrides_repository import (
    SqlAlchemyXBRLMappingOverridesRepository,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.services.xbrl_mapping_overrides import MappingOverrideRule, OverrideScope


class _DummyResult:
    """Minimal result wrapper exposing `scalars()`."""

    def __init__(self, rows: Sequence[Any] | None = None) -> None:
        self._rows = list(rows or [])

    def scalars(self) -> _DummyResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _DummySession:
    """Minimal session-like object for testing query wiring."""

    def __init__(self) -> None:
        self._last_stmt: Any | None = None
        self._results: list[_DummyResult] = []

    def add_result(self, result: _DummyResult) -> None:
        self._results.append(result)

    async def execute(self, stmt: Any) -> _DummyResult:  # pragma: no cover - trivial glue
        self._last_stmt = stmt
        if self._results:
            return self._results.pop(0)
        return _DummyResult()

    @property
    def last_stmt(self) -> Any:
        return self._last_stmt


def test_repository_can_be_constructed_with_dummy_session() -> None:
    """Repository should accept a generic session-like object for construction."""
    session = _DummySession()
    repo = SqlAlchemyXBRLMappingOverridesRepository(session=session)
    assert repo is not None


async def test_list_all_rules_returns_mapping_override_rules() -> None:
    """list_all_rules() should return MappingOverrideRule instances."""
    session = _DummySession()
    dummy_rule = MappingOverrideRule(
        rule_id="r1",
        scope=OverrideScope.GLOBAL,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_2024",
        match_cik=None,
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={},
        target_metric=CanonicalStatementMetric.REVENUE,
        is_suppression=False,
        priority=0,
    )

    session.add_result(_DummyResult(rows=[dummy_rule]))

    repo = SqlAlchemyXBRLMappingOverridesRepository(session=session)

    rules = await repo.list_all_rules()
    assert len(rules) == 1
    assert isinstance(rules[0], MappingOverrideRule)
    assert rules[0].rule_id == "r1"


async def test_list_rules_for_concept_passes_concept_through() -> None:
    """list_rules_for_concept() should execute a query when invoked."""
    session = _DummySession()
    repo = SqlAlchemyXBRLMappingOverridesRepository(session=session)

    session.add_result(_DummyResult(rows=[]))

    rules = await repo.list_rules_for_concept(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
    )

    assert rules == []
    assert session.last_stmt is not None
