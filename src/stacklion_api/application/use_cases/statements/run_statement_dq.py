# src/stacklion_api/application/use_cases/statements/run_statement_dq.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: run data-quality checks for a single statement identity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from stacklion_api.application.schemas.dto.edgar_dq import RunStatementDQResultDTO
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.repositories.edgar_dq_repository import (
    EdgarDQRepository as EdgarDQRepositoryProtocol,
)
from stacklion_api.domain.interfaces.repositories.edgar_facts_repository import (
    EdgarFactsRepository as EdgarFactsRepositoryProtocol,
)


@dataclass(slots=True)
class RunStatementDQRequest:
    """Request parameters for running DQ on a statement."""

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int

    rule_set_version: str = "v1"
    scope_type: str = "STATEMENT"
    history_lookback: int = 4  # prior points to inspect for trend checks


class RunStatementDQUseCase:
    """Run data-quality checks for a normalized statement and persist results.

    This use case:
        * Locates the target normalized statement and its persisted facts.
        * Runs the fact-level DQ engine for the requested rule-set and scope.
        * Persists the DQ run, fact-quality flags, and anomalies in a single
          transaction.
        * Returns a summary DTO suitable for HTTP presentation.

    Args:
        uow: UnitOfWork providing transactional access to the EDGAR fact store,
            DQ repositories, and statement metadata repositories.

    Returns:
        RunStatementDQResultDTO when :meth:`execute` is called.

    Raises:
        EdgarNotFound:
            If the target statement or its facts cannot be located.
        EdgarMappingError:
            If the request is structurally invalid or domain invariants fail.
        EdgarIngestionError:
            If an upstream ingestion or persistence error occurs during the run.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        facts_repo_type: type[EdgarFactsRepositoryProtocol] = EdgarFactsRepositoryProtocol,
        dq_repo_type: type[EdgarDQRepositoryProtocol] = EdgarDQRepositoryProtocol,
    ) -> None:
        """Initialize the use case.

        Args:
            uow: Factory that creates unit-of-work instances bound to a
                database session for this use case.
            dq_repo_type: Concrete `EdgarDQRepository` implementation used to
                persist DQ runs, fact quality flags, and anomalies.
            facts_repo_type: Concrete `EdgarFactsRepository` implementation used
                to read normalized facts for the target statement version.
        """
        self._uow = uow
        self._facts_repo_type = facts_repo_type
        self._dq_repo_type = dq_repo_type

    async def execute(self, req: RunStatementDQRequest) -> RunStatementDQResultDTO:
        """Run data-quality and persist the DQ run + artifacts."""
        identity = NormalizedStatementIdentity(
            cik=req.cik.strip(),
            statement_type=req.statement_type,
            fiscal_year=req.fiscal_year,
            fiscal_period=req.fiscal_period,
            version_sequence=req.version_sequence,
        )

        if not identity.cik:
            raise EdgarIngestionError(
                "CIK must not be empty for DQ evaluation.",
                details={"cik": req.cik},
            )

        async with self._uow as tx:
            facts_repo: EdgarFactsRepositoryProtocol = tx.get_repository(self._facts_repo_type)
            dq_repo: EdgarDQRepositoryProtocol = tx.get_repository(self._dq_repo_type)

            facts = await facts_repo.list_facts_for_statement(identity=identity)
            if not facts:
                raise EdgarIngestionError(
                    "Cannot run DQ: no facts exist for the target statement identity.",
                    details={
                        "cik": identity.cik,
                        "statement_type": identity.statement_type.value,
                        "fiscal_year": identity.fiscal_year,
                        "fiscal_period": identity.fiscal_period.value,
                        "version_sequence": identity.version_sequence,
                    },
                )

            fact_quality, anomalies = await self._evaluate_rules(
                identity=identity,
                facts=facts,
                facts_repo=facts_repo,
                history_lookback=req.history_lookback,
            )

            dq_run_id = str(uuid4())
            executed_at = datetime.now(tz=UTC)

            dq_run = EdgarDQRun(
                dq_run_id=dq_run_id,
                statement_identity=identity,
                rule_set_version=req.rule_set_version,
                scope_type=req.scope_type,
                executed_at=executed_at,
            )

            await dq_repo.create_run(
                run=dq_run,
                fact_quality=fact_quality,
                anomalies=anomalies,
            )

            await tx.commit()

        max_severity = _max_severity(fact_quality, anomalies)

        return RunStatementDQResultDTO(
            dq_run_id=dq_run_id,
            cik=identity.cik,
            statement_type=identity.statement_type,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period,
            version_sequence=identity.version_sequence,
            rule_set_version=req.rule_set_version,
            scope_type=req.scope_type,
            history_lookback=req.history_lookback,
            executed_at=executed_at,
            facts_evaluated=len(fact_quality),
            anomaly_count=len(anomalies),
            max_severity=max_severity,
        )

    # ------------------------------------------------------------------ #
    # Rule evaluation                                                    #
    # ------------------------------------------------------------------ #

    async def _evaluate_rules(
        self,
        *,
        identity: NormalizedStatementIdentity,
        facts: Sequence[EdgarNormalizedFact],
        facts_repo: EdgarFactsRepositoryProtocol,
        history_lookback: int,
    ) -> tuple[list[EdgarFactQuality], list[EdgarDQAnomaly]]:
        """Evaluate basic DQ rules over a set of facts."""
        fq_results: list[EdgarFactQuality] = []
        anomaly_results: list[EdgarDQAnomaly] = []

        for fact in facts:
            is_present = True
            is_non_negative = fact.value >= Decimal("0")
            is_consistent_with_history = None

            severity = MaterialityClass.NONE

            if not is_non_negative:
                severity = MaterialityClass.LOW
                anomaly_results.append(
                    EdgarDQAnomaly(
                        dq_run_id="",
                        statement_identity=identity,
                        metric_code=fact.metric_code,
                        dimension_key=fact.dimension_key,
                        rule_code="NON_NEGATIVE",
                        severity=MaterialityClass.LOW,
                        message="Metric value is negative; expected non-negative.",
                        details={"value": str(fact.value)},
                    ),
                )

            history = await facts_repo.list_facts_history(
                cik=identity.cik,
                statement_type=identity.statement_type.value,
                metric_code=fact.metric_code,
                limit=history_lookback,
            )

            if history:
                last = history[-1]
                if last.value != Decimal("0"):
                    change_ratio = (fact.value - last.value) / last.value
                    if abs(change_ratio) > Decimal("5"):
                        is_consistent_with_history = False
                        severity = max(severity, MaterialityClass.MEDIUM, key=_severity_rank)
                        anomaly_results.append(
                            EdgarDQAnomaly(
                                dq_run_id="",
                                statement_identity=identity,
                                metric_code=fact.metric_code,
                                dimension_key=fact.dimension_key,
                                rule_code="HISTORY_SPIKE",
                                severity=MaterialityClass.MEDIUM,
                                message="Metric exhibits large change relative to history.",
                                details={
                                    "previous_value": str(last.value),
                                    "current_value": str(fact.value),
                                    "change_ratio": str(change_ratio),
                                },
                            ),
                        )
                    else:
                        is_consistent_with_history = True
                else:
                    is_consistent_with_history = None
            else:
                is_consistent_with_history = None

            fq_results.append(
                EdgarFactQuality(
                    dq_run_id="",
                    statement_identity=identity,
                    metric_code=fact.metric_code,
                    dimension_key=fact.dimension_key,
                    severity=severity,
                    is_present=is_present,
                    is_non_negative=is_non_negative,
                    is_consistent_with_history=is_consistent_with_history,
                    has_known_issue=False,
                    details=None,
                ),
            )

        return fq_results, anomaly_results


def _severity_rank(severity: MaterialityClass) -> int:
    """Return a stable numeric rank for severity."""
    order = {
        MaterialityClass.NONE: 0,
        MaterialityClass.LOW: 1,
        MaterialityClass.MEDIUM: 2,
        MaterialityClass.HIGH: 3,
    }
    return order.get(severity, 0)


def _max_severity(
    fact_quality: Sequence[EdgarFactQuality],
    anomalies: Sequence[EdgarDQAnomaly],
) -> MaterialityClass | None:
    """Compute the maximum severity across fact-quality and anomalies."""
    severities: list[MaterialityClass] = []
    severities.extend(fq.severity for fq in fact_quality)
    severities.extend(a.severity for a in anomalies)

    if not severities:
        return None

    return max(severities, key=_severity_rank)
