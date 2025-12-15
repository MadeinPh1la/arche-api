# src/arche_api/application/use_cases/statements/get_statement_with_dq_overlay.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: retrieve a statement with fact + DQ overlay.

Purpose:
    Given a statement identity, return a read-model overlay combining:

        * Statement metadata (accounting_standard, statement_date, currency).
        * Persistent facts from the fact store.
        * Latest DQ run metadata, fact-quality flags, and anomalies.

Layer:
    application/use_cases/statements
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from arche_api.application.schemas.dto.edgar_dq import (
    DQAnomalyDTO,
    FactQualityDTO,
    NormalizedFactDTO,
    StatementDQOverlayDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError
from arche_api.domain.interfaces.repositories.edgar_dq_repository import (
    EdgarDQRepository as EdgarDQRepositoryProtocol,
)
from arche_api.domain.interfaces.repositories.edgar_facts_repository import (
    EdgarFactsRepository as EdgarFactsRepositoryProtocol,
)
from arche_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)


@dataclass(slots=True)
class GetStatementWithDQOverlayRequest:
    """Request parameters for retrieving a statement with DQ overlay."""

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int


class GetStatementWithDQOverlayUseCase:
    """Retrieve a normalized statement and attach DQ overlay information.

    Args:
        uow: Unit of work providing EDGAR statements, normalized facts, and
            data-quality repositories.

    Methods:
        execute: Load the requested statement, look up the latest DQ run and
            fact-level quality records, and project them into a
            StatementWithDQOverlayDTO.

    Raises:
        EdgarIngestionError: If the statement identity cannot be resolved
            from the repositories.
        EdgarMappingError: If the request parameters are invalid.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        statements_repo_type: type[
            EdgarStatementsRepositoryProtocol
        ] = EdgarStatementsRepositoryProtocol,
        facts_repo_type: type[EdgarFactsRepositoryProtocol] = EdgarFactsRepositoryProtocol,
        dq_repo_type: type[EdgarDQRepositoryProtocol] = EdgarDQRepositoryProtocol,
    ) -> None:
        """Initialize the use case with its dependencies.

        Args:
            uow:
                Unit-of-work providing transactional boundaries.
            statements_repo_type:
                Repository interface/key used to resolve the statements repo.
            facts_repo_type:
                Repository interface/key used to resolve the facts repo.
            dq_repo_type:
                Repository interface/key used to resolve the DQ repo.
        """
        self._uow = uow
        self._statements_repo_type = statements_repo_type
        self._facts_repo_type = facts_repo_type
        self._dq_repo_type = dq_repo_type

    async def execute(
        self,
        req: GetStatementWithDQOverlayRequest,
    ) -> StatementDQOverlayDTO:
        """Return a statement-level fact + DQ overlay."""
        identity = NormalizedStatementIdentity(
            cik=req.cik.strip(),
            statement_type=req.statement_type,
            fiscal_year=req.fiscal_year,
            fiscal_period=req.fiscal_period,
            version_sequence=req.version_sequence,
        )

        if not identity.cik:
            raise EdgarIngestionError(
                "CIK must not be empty for DQ overlay retrieval.",
                details={"cik": req.cik},
            )

        async with self._uow as tx:
            statements_repo: EdgarStatementsRepositoryProtocol = tx.get_repository(
                self._statements_repo_type,
            )
            facts_repo: EdgarFactsRepositoryProtocol = tx.get_repository(
                self._facts_repo_type,
            )
            dq_repo: EdgarDQRepositoryProtocol = tx.get_repository(self._dq_repo_type)

            statement = await self._fetch_statement(statements_repo, identity)
            facts = await facts_repo.list_facts_for_statement(identity=identity)
            dq_run = await dq_repo.latest_run_for_statement(identity=identity)
            fact_quality = await dq_repo.list_fact_quality_for_statement(identity=identity)
            anomalies = await dq_repo.list_anomalies_for_statement(identity=identity)

        facts_dto = [_map_fact_to_dto(f) for f in facts]
        fq_dto = [_map_fq_to_dto(fq) for fq in fact_quality]
        anomalies_dto = [_map_anomaly_to_dto(a) for a in anomalies]

        max_severity = _max_severity(fact_quality_severity=fq_dto, anomalies=anomalies_dto)

        return StatementDQOverlayDTO(
            cik=identity.cik,
            statement_type=identity.statement_type,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period,
            version_sequence=identity.version_sequence,
            accounting_standard=statement.accounting_standard,
            statement_date=statement.statement_date,
            currency=statement.currency,
            dq_run_id=dq_run.dq_run_id if dq_run is not None else None,
            dq_rule_set_version=dq_run.rule_set_version if dq_run is not None else None,
            dq_executed_at=dq_run.executed_at if dq_run is not None else None,
            max_severity=max_severity,
            facts=facts_dto,
            fact_quality=fq_dto,
            anomalies=anomalies_dto,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    async def _fetch_statement(
        self,
        repo: EdgarStatementsRepositoryProtocol,
        identity: NormalizedStatementIdentity,
    ) -> EdgarStatementVersion:
        """Fetch the target statement version entity, validating identity."""
        versions = await repo.list_statement_versions_for_company(
            cik=identity.cik,
            statement_type=identity.statement_type,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period,
        )

        for v in versions:
            if v.version_sequence == identity.version_sequence:
                return v

        raise EdgarIngestionError(
            "No statement version found for DQ overlay retrieval.",
            details={
                "cik": identity.cik,
                "statement_type": identity.statement_type.value,
                "fiscal_year": identity.fiscal_year,
                "fiscal_period": identity.fiscal_period.value,
                "version_sequence": identity.version_sequence,
            },
        )


def _map_fact_to_dto(domain_fact: Any) -> NormalizedFactDTO:
    """Map a fact-like object into a NormalizedFactDTO.

    Duck-typed: relies on attributes instead of concrete domain classes.
    """
    return NormalizedFactDTO(
        cik=domain_fact.cik,
        statement_type=domain_fact.statement_type,
        accounting_standard=domain_fact.accounting_standard,
        fiscal_year=domain_fact.fiscal_year,
        fiscal_period=domain_fact.fiscal_period,
        statement_date=domain_fact.statement_date,
        version_sequence=domain_fact.version_sequence,
        metric_code=domain_fact.metric_code,
        metric_label=getattr(domain_fact, "metric_label", None),
        unit=domain_fact.unit,
        period_start=getattr(domain_fact, "period_start", None),
        period_end=domain_fact.period_end,
        value=str(domain_fact.value),
        dimension_key=domain_fact.dimension_key,
        dimensions=dict(getattr(domain_fact, "dimensions", {})),
        source_line_item=getattr(domain_fact, "source_line_item", None),
    )


def _map_fq_to_dto(domain_fq: Any) -> FactQualityDTO:
    """Map a fact-quality-like object into a FactQualityDTO."""
    identity = domain_fq.statement_identity

    details = getattr(domain_fq, "details", None)
    details_str: dict[str, str] | None
    details_str = None if details is None else {str(k): str(v) for k, v in details.items()}

    return FactQualityDTO(
        cik=identity.cik,
        statement_type=identity.statement_type,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period,
        version_sequence=identity.version_sequence,
        metric_code=domain_fq.metric_code,
        dimension_key=domain_fq.dimension_key,
        severity=domain_fq.severity,
        is_present=domain_fq.is_present,
        is_non_negative=domain_fq.is_non_negative,
        is_consistent_with_history=domain_fq.is_consistent_with_history,
        has_known_issue=domain_fq.has_known_issue,
        details=details_str,
    )


def _map_anomaly_to_dto(domain_anomaly: Any) -> DQAnomalyDTO:
    """Map an anomaly-like object into a DQAnomalyDTO."""
    details = getattr(domain_anomaly, "details", None)
    details_str: dict[str, str] | None
    details_str = None if details is None else {str(k): str(v) for k, v in details.items()}

    return DQAnomalyDTO(
        dq_run_id=getattr(domain_anomaly, "dq_run_id", ""),
        metric_code=getattr(domain_anomaly, "metric_code", ""),
        dimension_key=getattr(domain_anomaly, "dimension_key", ""),
        rule_code=getattr(domain_anomaly, "rule_code", ""),
        severity=getattr(domain_anomaly, "severity", None),
        message=getattr(domain_anomaly, "message", ""),
        details=details_str,
    )


def _max_severity(
    *,
    fact_quality_severity: Sequence[FactQualityDTO],
    anomalies: Sequence[DQAnomalyDTO],
) -> MaterialityClass | None:
    """Compute max severity across fact-quality DTOs and anomaly DTOs."""
    severities: list[MaterialityClass] = [fq.severity for fq in fact_quality_severity] + [
        a.severity for a in anomalies
    ]

    if not severities:
        return None

    order = {
        MaterialityClass.NONE: 0,
        MaterialityClass.LOW: 1,
        MaterialityClass.MEDIUM: 2,
        MaterialityClass.HIGH: 3,
    }
    return max(severities, key=lambda s: order.get(s, 0))
