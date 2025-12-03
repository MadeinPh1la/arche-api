# src/stacklion_api/domain/interfaces/repositories/edgar_facts_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR normalized facts repository interface.

Purpose:
    Define persistence and query operations for normalized EDGAR facts
    derived from canonical statement payloads. Implementations are expected
    to provide deterministic ordering guarantees suitable for financial
    modeling and data-quality evaluation.

Layer:
    domain/interfaces/repositories

Notes:
    Implementations live in the adapters/infrastructure layers (e.g.,
    SQLAlchemy repositories) and must translate DB/driver errors into domain
    exceptions where appropriate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact


class EdgarFactsRepository(Protocol):
    """Protocol for repositories managing EDGAR normalized facts."""

    async def replace_facts_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        facts: Sequence[EdgarNormalizedFact],
    ) -> None:
        """Replace all facts for a given statement identity.

        Implementations must:
            - Remove any existing facts for the exact statement identity
              (including version_sequence).
            - Insert the provided facts in an idempotent fashion.
            - Preserve deterministic ordering for subsequent queries by
              enforcing a stable identity and index scheme.

        Args:
            identity:
                Normalized statement identity (including version_sequence).
            facts:
                Collection of facts to persist for the statement identity.
        """

    async def list_facts_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        metric_filter: Sequence[str] | None = None,
    ) -> Sequence[EdgarNormalizedFact]:
        """Return all facts for a given statement identity.

        Args:
            identity:
                Normalized statement identity (including version_sequence).
            metric_filter:
                Optional subset of metric codes to restrict the result to.
                When None, all metrics are returned.

        Returns:
            A deterministically ordered sequence of facts. Implementations
            SHOULD document the ordering, for example:

                - metric_code ASC
                - dimension_key ASC
        """

    async def list_facts_history(
        self,
        *,
        cik: str,
        statement_type: str,
        metric_code: str,
        limit: int = 8,
    ) -> Sequence[EdgarNormalizedFact]:
        """Return a small historical slice of facts for a metric.

        This method is intended for history-based DQ rules.

        Args:
            cik:
                Company CIK.
            statement_type:
                Statement type code (matching StatementType.value).
            metric_code:
                Metric code to fetch history for.
            limit:
                Maximum number of prior facts to return. Implementations
                SHOULD return the most recent facts, ordered ascending by
                statement_date / version_sequence so that callers can use
                the last item as the immediate prior observation.
        """


__all__ = ["EdgarFactsRepository"]
