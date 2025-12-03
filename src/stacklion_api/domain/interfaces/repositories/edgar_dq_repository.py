# src/stacklion_api/domain/interfaces/repositories/edgar_dq_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR data-quality repository interfaces.

Purpose:
    Define persistence and query operations for EDGAR data-quality runs,
    fact-level quality flags, and rule-level anomalies.

Layer:
    domain/interfaces/repositories

Notes:
    Implementations live in adapters/infrastructure and must ensure that
    the access patterns remain deterministic and efficient for the intended
    DQ use cases.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.enums.edgar import MaterialityClass


class EdgarDQRepository(Protocol):
    """Protocol for repositories managing EDGAR data-quality artifacts."""

    async def create_run(
        self,
        run: EdgarDQRun,
        fact_quality: Sequence[EdgarFactQuality],
        anomalies: Sequence[EdgarDQAnomaly],
    ) -> None:
        """Persist a DQ run and its associated artifacts.

        Implementations must:
            - Persist the run record first.
            - Persist all fact quality records and anomalies associated with
              the run in a single transactional unit when possible.
            - Ensure that repeated calls with the same ``dq_run_id`` are
              either idempotent or rejected in a well-defined manner.
        """

    async def latest_run_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> EdgarDQRun | None:
        """Return the latest DQ run for a given statement identity.

        Args:
            identity:
                Normalized statement identity (including version_sequence).

        Returns:
            The most recent DQ run for the statement, or None if no run
            exists.
        """

    async def list_anomalies_for_run(
        self,
        dq_run_id: str,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        """List anomalies for a given DQ run.

        Args:
            dq_run_id:
                Identifier of the DQ run.
            min_severity:
                Optional severity threshold. When provided, only anomalies with
                severity >= min_severity SHOULD be returned.
            limit:
                Maximum number of anomalies to return.

        Returns:
            A deterministically ordered list of anomalies, for example ordered
            by (severity DESC, rule_code ASC, anomaly_id ASC).
        """

    async def list_anomalies_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        """List anomalies associated with a statement identity.

        Implementations SHOULD use the most recent DQ run for the identity
        when multiple runs exist.

        Args:
            identity:
                Normalized statement identity (including version_sequence).
            min_severity:
                Optional minimum severity filter.
            limit:
                Maximum number of anomalies to return.
        """

    async def list_fact_quality_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> list[EdgarFactQuality]:
        """Return fact-level quality information for a statement identity.

        Args:
            identity:
                Normalized statement identity (including version_sequence).

        Returns:
            A deterministically ordered list of fact quality records.
        """


__all__ = ["EdgarDQRepository"]
