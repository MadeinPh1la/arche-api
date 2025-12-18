# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Run reconciliation for a statement identity.

Purpose:
    Orchestrate the end-to-end reconciliation flow for an EDGAR statement
    identity tuple, bridging:
        - Statement versions / normalized payloads (statements repo)
        - Optional normalized facts (facts repo)
        - Domain reconciliation engine (E11-A)
        - Persistent reconciliation ledger (E11-C)

Layer:
    application/use_cases/reconciliation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from arche_api.application.schemas.dto.reconciliation import (
    ReconciliationResultDTO,
    RunReconciliationOptionsDTO,
    RunReconciliationRequestDTO,
    RunReconciliationResponseDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult, ReconciliationRule
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.enums.edgar_reconciliation import ReconciliationRuleCategory
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from arche_api.domain.interfaces.repositories.edgar_facts_repository import (
    EdgarFactsRepository as EdgarFactsRepositoryPort,
)
from arche_api.domain.interfaces.repositories.edgar_reconciliation_checks_repository import (
    EdgarReconciliationChecksRepository as EdgarReconciliationChecksRepositoryPort,
)
from arche_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryPort,
)
from arche_api.domain.services.reconciliation_engine import ReconciliationEngine


def _statement_types_for_reconciliation() -> tuple[StatementType, ...]:
    """Return the statement types to reconcile across.

    Notes:
        This helper keeps ordering deterministic and tolerates enum naming
        differences across iterations.
    """
    preferred_names = (
        "INCOME_STATEMENT",
        "BALANCE_SHEET",
        "CASH_FLOW_STATEMENT",
        "CASH_FLOW",
    )

    out: list[StatementType] = []
    for name in preferred_names:
        member = getattr(StatementType, name, None)
        if member is not None and member not in out:
            out.append(member)

    if not out:
        out = list(StatementType)

    return tuple(out)


@dataclass(frozen=True, slots=True)
class _ResolvedInputs:
    payloads: tuple[CanonicalStatementPayload, ...]
    facts_by_identity: dict[NormalizedStatementIdentity, tuple[EdgarNormalizedFact, ...]]


class RunReconciliationForStatementIdentityUseCase:
    """Run reconciliation for a statement identity tuple.

    Args:
        uow: Application UnitOfWork used to resolve repositories and manage the transaction.
        engine: Optional domain reconciliation engine. When omitted, a default engine is used.

    Returns:
        RunReconciliationResponseDTO containing a reconciliation_run_id, executed_at, and results.

    Raises:
        EdgarMappingError: When request parameters are invalid.
        EdgarIngestionError: When statement versions/payloads cannot be resolved.
    """

    def __init__(self, *, uow: UnitOfWork, engine: ReconciliationEngine | None = None) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork used to resolve repositories and manage the transaction.
            engine: Optional domain reconciliation engine instance.
        """
        self._uow = uow
        self._engine = engine or ReconciliationEngine()

    async def execute(self, req: RunReconciliationRequestDTO) -> RunReconciliationResponseDTO:
        """Execute reconciliation for the requested identity.

        Args:
            req: Application-layer request DTO describing the target identity and options.

        Returns:
            A RunReconciliationResponseDTO including a persisted run_id and deterministically ordered results.

        Raises:
            EdgarMappingError: When request parameters are invalid.
            EdgarIngestionError: When no payloads can be resolved for the requested identity/window.
        """
        cik = _normalize_cik(req.cik)
        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for reconciliation run.",
                details={"fiscal_year": req.fiscal_year},
            )

        try:
            statement_type = StatementType(req.statement_type)
        except Exception as exc:  # noqa: BLE001
            raise EdgarMappingError(
                "Invalid statement_type for reconciliation run.",
                details={"statement_type": req.statement_type},
            ) from exc

        try:
            fiscal_period = FiscalPeriod(req.fiscal_period)
        except Exception as exc:  # noqa: BLE001
            raise EdgarMappingError(
                "Invalid fiscal_period for reconciliation run.",
                details={"fiscal_period": req.fiscal_period},
            ) from exc

        options = req.options or RunReconciliationOptionsDTO()
        if options.fiscal_year_window < 0 or options.fiscal_year_window > 20:
            raise EdgarMappingError(
                "fiscal_year_window must be between 0 and 20.",
                details={"fiscal_year_window": options.fiscal_year_window},
            )

        reconciliation_run_id = str(uuid4())
        executed_at = datetime.now(tz=UTC)

        async with self._uow as tx:
            statements_repo = _get_statements_repo(tx)
            facts_repo = _get_facts_repo(tx)
            ledger_repo = _get_ledger_repo(tx)

            resolved = await _resolve_payloads_and_facts(
                statements_repo=statements_repo,
                facts_repo=facts_repo,
                cik=cik,
                statement_type=statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=fiscal_period,
                options=options,
            )

            rules = _build_default_rules(options.rule_categories)

            domain_results = self._engine.run(
                rules=rules,
                statements=resolved.payloads,
                facts_by_identity=resolved.facts_by_identity if options.deep else None,
            )

            await ledger_repo.append_results(
                reconciliation_run_id=reconciliation_run_id,
                executed_at=executed_at,
                results=domain_results,
            )
            await tx.commit()

        app_results = tuple(_map_result_to_dto(r) for r in domain_results)
        return RunReconciliationResponseDTO(
            reconciliation_run_id=reconciliation_run_id,
            executed_at=executed_at,
            results=app_results,
        )


def _normalize_cik(raw: str) -> str:
    """Normalize and validate a CIK string."""
    cik = raw.strip()
    if not cik:
        raise EdgarMappingError("CIK must not be empty for reconciliation run.")
    if not cik.isdigit():
        raise EdgarMappingError(
            "CIK must contain only digits for reconciliation run.",
            details={"cik": raw},
        )
    return cik


def _get_statements_repo(tx: Any) -> EdgarStatementsRepositoryPort:
    if hasattr(tx, "statements_repo"):
        return cast(EdgarStatementsRepositoryPort, tx.statements_repo)
    repo_any = tx.get_repository(EdgarStatementsRepositoryPort)
    return cast(EdgarStatementsRepositoryPort, repo_any)


def _get_facts_repo(tx: Any) -> EdgarFactsRepositoryPort:
    if hasattr(tx, "facts_repo"):
        return cast(EdgarFactsRepositoryPort, tx.facts_repo)
    repo_any = tx.get_repository(EdgarFactsRepositoryPort)
    return cast(EdgarFactsRepositoryPort, repo_any)


def _get_ledger_repo(tx: Any) -> EdgarReconciliationChecksRepositoryPort:
    if hasattr(tx, "reconciliation_checks_repo"):
        return cast(EdgarReconciliationChecksRepositoryPort, tx.reconciliation_checks_repo)
    repo_any = tx.get_repository(EdgarReconciliationChecksRepositoryPort)
    return cast(EdgarReconciliationChecksRepositoryPort, repo_any)


async def _resolve_payloads_and_facts(
    *,
    statements_repo: EdgarStatementsRepositoryPort,
    facts_repo: EdgarFactsRepositoryPort,
    cik: str,
    statement_type: StatementType,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    options: RunReconciliationOptionsDTO,
) -> _ResolvedInputs:
    years = list(range(fiscal_year - options.fiscal_year_window, fiscal_year + 1))
    payloads: list[CanonicalStatementPayload] = []
    facts_by_identity: dict[NormalizedStatementIdentity, tuple[EdgarNormalizedFact, ...]] = {}

    statement_types = _statement_types_for_reconciliation()

    for year in sorted(years):
        for st in statement_types:
            versions = await statements_repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=st,
                fiscal_year=year,
                fiscal_period=fiscal_period,
            )
            if not versions:
                continue

            latest = max(versions, key=lambda v: v.version_sequence)
            payload = latest.normalized_payload
            if payload is None:
                continue

            payloads.append(payload)

            if options.deep:
                identity = NormalizedStatementIdentity(
                    cik=payload.cik,
                    statement_type=payload.statement_type,
                    fiscal_year=payload.fiscal_year,
                    fiscal_period=payload.fiscal_period,
                    version_sequence=payload.source_version_sequence,
                )
                facts = await facts_repo.list_facts_for_statement(identity)
                facts_by_identity[identity] = tuple(facts)

    if not payloads:
        raise EdgarIngestionError(
            "No normalized statement payloads found for reconciliation run.",
            details={
                "cik": cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
                "fiscal_year_window": options.fiscal_year_window,
            },
        )

    payloads.sort(
        key=lambda p: (
            p.cik,
            p.statement_type.value,
            p.fiscal_year,
            p.fiscal_period.value,
            p.source_version_sequence,
        )
    )

    return _ResolvedInputs(payloads=tuple(payloads), facts_by_identity=facts_by_identity)


def _map_result_to_dto(result: ReconciliationResult) -> ReconciliationResultDTO:
    return ReconciliationResultDTO(
        statement_identity=result.statement_identity,
        rule_id=result.rule_id,
        rule_category=result.rule_category,
        status=result.status,
        severity=str(result.severity),
        expected_value=result.expected_value,
        actual_value=result.actual_value,
        delta=result.delta,
        dimension_key=result.dimension_key,
        dimension_labels=result.dimension_labels,
        notes=result.notes,
    )


def _build_default_rules(
    categories: tuple[ReconciliationRuleCategory, ...] | None,
) -> tuple[ReconciliationRule, ...]:
    """Build a conservative default rule set.

    Rules are included only when the required CanonicalStatementMetric enum
    members exist in the current codebase. This avoids hard failures when
    registries evolve.
    """
    from decimal import Decimal

    from arche_api.domain.entities.edgar_reconciliation import (
        CalendarReconciliationRule,
        IdentityReconciliationRule,
        RollforwardReconciliationRule,
    )
    from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
    from arche_api.domain.enums.edgar import MaterialityClass

    def include(cat: ReconciliationRuleCategory) -> bool:
        return categories is None or cat in categories

    def metric(name: str) -> Any:
        return getattr(CanonicalStatementMetric, name)

    def has_metric(name: str) -> bool:
        return hasattr(CanonicalStatementMetric, name)

    rules: list[ReconciliationRule] = []

    # IDENTITY: Assets = Liabilities + Equity (classic BS identity).
    if (
        include(ReconciliationRuleCategory.IDENTITY)
        and has_metric("ASSETS")
        and has_metric("LIABILITIES")
        and has_metric("EQUITY")
    ):
        rules.append(
            IdentityReconciliationRule(
                rule_id="bs_assets_eq_liab_plus_equity",
                name="Balance sheet identity: Assets = Liabilities + Equity",
                category=ReconciliationRuleCategory.IDENTITY,
                severity=MaterialityClass.HIGH,
                lhs_metrics=(metric("ASSETS"),),
                rhs_metrics=(metric("LIABILITIES"), metric("EQUITY")),
                tolerance=Decimal("1.00"),
                applicable_statement_types=None,
            )
        )

    # ROLLFORWARD example: Opening Cash + Net Change = Ending Cash.
    if (
        include(ReconciliationRuleCategory.ROLLFORWARD)
        and has_metric("CASH_BEGINNING")
        and has_metric("NET_CASH_CHANGE")
        and has_metric("CASH_ENDING")
    ):
        rules.append(
            RollforwardReconciliationRule(
                rule_id="cf_cash_rollforward",
                name="Cash rollforward: begin + change = end",
                category=ReconciliationRuleCategory.ROLLFORWARD,
                severity=MaterialityClass.MEDIUM,
                opening_metric=metric("CASH_BEGINNING"),
                flow_metrics=(metric("NET_CASH_CHANGE"),),
                closing_metric=metric("CASH_ENDING"),
                period_granularity=None,
                tolerance=Decimal("1.00"),
            )
        )

    # CALENDAR: allow common FYEs (Dec/Sept/Jun/Mar) by default.
    if include(ReconciliationRuleCategory.CALENDAR):
        rules.append(
            CalendarReconciliationRule(
                rule_id="calendar_allowed_fye_months_default",
                name="Calendar sanity: allowed fiscal year-end months",
                category=ReconciliationRuleCategory.CALENDAR,
                severity=MaterialityClass.LOW,
                allowed_fye_months=(12, 9, 6, 3),
                allow_53_week=True,
            )
        )

    rules.sort(key=lambda r: (r.category.value, getattr(r, "rule_id", "")))
    return tuple(rules)
