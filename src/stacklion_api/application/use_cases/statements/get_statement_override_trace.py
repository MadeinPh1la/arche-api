# src/stacklion_api/application/use_cases/statements/get_statement_override_trace.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Use case: Inspect XBRL mapping overrides for a statement identity.

Purpose:
    Provide a deterministic, statement-scoped view of how XBRL mapping
    overrides affect canonical metric resolution for a specific normalized
    EDGAR statement version.

    The use case:
        * Resolves the target statement version for a (CIK, type, year,
          period, version_sequence) identity.
        * Loads XBRL mapping override rules via the application UnitOfWork.
        * Builds a NormalizationContext and delegates to the pure-domain
          XBRLOverrideObservabilityService to evaluate overrides.
        * Projects the domain-level StatementOverrideObservability into an
          application DTO suitable for HTTP presentation.

Layer:
    application/use_cases/statements

Notes:
    - This use case is read-only and does not perform any writes.
    - It does not log or emit metrics directly; the API layer is responsible
      for attaching structured logs around execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Any, cast

from stacklion_api.application.schemas.dto.xbrl_overrides import (
    OverrideDecisionDTO,
    OverrideTraceEntryDTO,
    StatementOverrideTraceDTO,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.entities.xbrl_override_observability import (
    EffectiveOverrideDecisionSummary,
    OverrideTraceEntry,
    StatementOverrideObservability,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from stacklion_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository as XBRLMappingOverridesRepositoryProtocol,
)
from stacklion_api.domain.services.edgar_normalization import EdgarFact, NormalizationContext
from stacklion_api.domain.services.xbrl_mapping_overrides import MappingOverrideRule
from stacklion_api.domain.services.xbrl_override_observability import (
    XBRLOverrideObservabilityService,
)


@dataclass(frozen=True)
class GetStatementOverrideTraceRequest:
    """Request parameters for override observability on a statement.

    Attributes:
        cik:
            Company CIK as a normalized, zero-padded string.
        statement_type:
            Statement type (income statement, balance sheet, etc.).
        fiscal_year:
            Fiscal year associated with the statement (must be > 0).
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2, Q3, Q4).
        version_sequence:
            Specific statement version sequence to inspect.
        gaap_concept:
            Optional GAAP/IFRS concept filter (e.g., "us-gaap:Revenues").
            When provided, the override rule set is restricted to rules that
            target the given concept.
        canonical_metric_code:
            Optional canonical metric filter (e.g., "REVENUE", "NET_INCOME").
            When provided, the override rule set is restricted to rules whose
            base_metric matches the given canonical code.
        dimension_key:
            Optional dimension key filter. The current implementation does
            not apply additional filtering by dimension_key at the domain
            layer; the field is preserved in the DTO for future extensions.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    gaap_concept: str | None = None
    canonical_metric_code: str | None = None
    dimension_key: str | None = None


class GetStatementOverrideTraceUseCase:
    """Use case for inspecting XBRL mapping overrides for a statement.

    Args:
        uow:
            Application UnitOfWork abstraction used to resolve repositories.

    Raises:
        EdgarMappingError:
            When request parameters are invalid or inconsistent (for example,
            empty CIK, non-positive fiscal_year, or invalid canonical metric
            code).
        EdgarIngestionError:
            When the requested statement identity cannot be resolved or the
            target version lacks a normalized payload.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow:
                Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow
        self._observability_service = XBRLOverrideObservabilityService()

    async def execute(self, req: GetStatementOverrideTraceRequest) -> StatementOverrideTraceDTO:
        """Execute the override observability flow.

        Args:
            req:
                Request parameters describing the target statement identity and
                optional filters.

        Returns:
            StatementOverrideTraceDTO describing the effective override
            decisions and evaluation trace for the requested statement.

        Raises:
            EdgarMappingError:
                When request parameters are invalid (e.g., empty CIK, invalid
                canonical metric code, non-positive fiscal_year).
            EdgarIngestionError:
                When the requested statement identity cannot be resolved or
                the target version lacks a normalized payload.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError(
                "CIK must not be empty for get_statement_override_trace().",
            )

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_statement_override_trace().",
                details={"fiscal_year": req.fiscal_year},
            )

        async with self._uow as tx:
            statements_repo = _get_edgar_statements_repository(tx)
            overrides_repo = _get_xbrl_mapping_overrides_repository(tx)

            statement_version = await _load_statement_version(
                repo=statements_repo,
                cik=cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
                version_sequence=req.version_sequence,
            )

            if statement_version.normalized_payload is None:
                raise EdgarIngestionError(
                    "Requested EDGAR statement version does not have a normalized payload.",
                    details={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "version_sequence": req.version_sequence,
                    },
                )

            taxonomy = statement_version.normalized_payload.source_taxonomy

            rules = await _load_override_rules(
                repo=overrides_repo,
                gaap_concept=req.gaap_concept,
                canonical_metric_code=req.canonical_metric_code,
                taxonomy=taxonomy,
            )

        context = _build_normalization_context_for_observability(
            statement_version=statement_version,
            accounting_standard=statement_version.accounting_standard,
            taxonomy=taxonomy,
            rules=rules,
        )

        observability = self._observability_service.inspect_overrides(context)

        dto = _map_observability_to_dto(
            observability=observability,
            dimension_key=req.dimension_key,
        )
        return dto


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_edgar_statements_repository(tx: Any) -> EdgarStatementsRepositoryProtocol:
    """Resolve the EDGAR statements repository via the UnitOfWork.

    Test doubles may expose `repo`, `statements_repo`, or `_repo` attributes
    instead of a full repository registry. Prefer those when present to keep
    tests and fakes simple.
    """
    if hasattr(tx, "repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.repo)
    if hasattr(tx, "statements_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.statements_repo)
    if hasattr(tx, "_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx._repo)

    module = import_module("stacklion_api.adapters.repositories.edgar_statements_repository")
    repo_type = module.EdgarStatementsRepository
    return cast(EdgarStatementsRepositoryProtocol, tx.get_repository(repo_type))


def _get_xbrl_mapping_overrides_repository(
    tx: Any,
) -> XBRLMappingOverridesRepositoryProtocol:
    """Resolve the XBRL mapping overrides repository via the UnitOfWork.

    Test doubles may expose `overrides_repo` or `xbrl_overrides_repo`
    attributes. Prefer those when present.
    """
    if hasattr(tx, "overrides_repo"):
        return cast(XBRLMappingOverridesRepositoryProtocol, tx.overrides_repo)
    if hasattr(tx, "xbrl_overrides_repo"):
        return cast(XBRLMappingOverridesRepositoryProtocol, tx.xbrl_overrides_repo)

    module = import_module(
        "stacklion_api.adapters.repositories.xbrl_mapping_overrides_repository",
    )
    repo_type = module.XBRLMappingOverridesRepository
    return cast(XBRLMappingOverridesRepositoryProtocol, tx.get_repository(repo_type))


async def _load_statement_version(
    *,
    repo: Any,
    cik: str,
    statement_type: StatementType,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    version_sequence: int,
) -> EdgarStatementVersion:
    """Load the target statement version for a given identity.

    This helper uses the existing list_statement_versions_for_company()
    contract and performs the version_sequence selection in the application
    layer. This avoids introducing new repository methods for the micro-phase.
    """
    versions: Sequence[EdgarStatementVersion] = await repo.list_statement_versions_for_company(
        cik=cik,
        statement_type=statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
    )

    if not versions:
        raise EdgarIngestionError(
            "No EDGAR statement versions found for requested identity.",
            details={
                "cik": cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
            },
        )

    for version in versions:
        if version.version_sequence == version_sequence:
            return version

    raise EdgarIngestionError(
        "Requested version_sequence does not exist for the statement identity.",
        details={
            "cik": cik,
            "statement_type": statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period.value,
            "version_sequence": version_sequence,
        },
    )


async def _load_override_rules(
    *,
    repo: XBRLMappingOverridesRepositoryProtocol,
    gaap_concept: str | None,
    canonical_metric_code: str | None,
    taxonomy: str,
) -> Sequence[MappingOverrideRule]:
    """Load and filter override rules for the requested slice.

    The repository is responsible for returning a superset of candidate rules.
    This helper applies additional filters based on GAAP concept and canonical
    metric code.
    """
    if gaap_concept:
        rules = await repo.list_rules_for_concept(concept=gaap_concept, taxonomy=taxonomy)
    else:
        rules = await repo.list_all_rules()

    if canonical_metric_code:
        try:
            metric_enum = CanonicalStatementMetric[canonical_metric_code]
        except KeyError as exc:
            raise EdgarMappingError(
                "Invalid canonical_metric_code for override trace.",
                details={"canonical_metric_code": canonical_metric_code},
            ) from exc

        filtered_rules: list[MappingOverrideRule] = []
        for rule in rules:
            base_metric = getattr(rule, "base_metric", None)
            if base_metric == metric_enum:
                filtered_rules.append(rule)

        rules = filtered_rules

    return rules


def _build_normalization_context_for_observability(
    *,
    statement_version: EdgarStatementVersion,
    accounting_standard: AccountingStandard,
    taxonomy: str,
    rules: Sequence[MappingOverrideRule],
) -> NormalizationContext:
    """Construct a NormalizationContext for the observability service.

    Notes:
        - This micro-phase does not rehydrate full EDGAR fact sets. The
          NormalizationContext is created with an empty fact sequence,
          which yields a deterministic but fact-agnostic observability
          summary (zero suppression/remap counts and empty per-metric maps
          when no candidate facts are present).
        - The override rule hierarchy and matching semantics remain fully
          enforced by the XBRLOverrideObservabilityService.
    """
    facts: Sequence[EdgarFact] = ()

    cik = getattr(statement_version, "cik", None)
    if cik is None:
        cik = statement_version.company.cik

    return NormalizationContext(
        cik=cik,
        statement_type=statement_version.statement_type,
        accounting_standard=accounting_standard,
        statement_date=statement_version.statement_date,
        fiscal_year=statement_version.fiscal_year,
        fiscal_period=statement_version.fiscal_period,
        currency=statement_version.currency,
        accession_id=statement_version.accession_id,
        taxonomy=taxonomy,
        version_sequence=statement_version.version_sequence,
        facts=facts,
        industry_code=getattr(statement_version, "industry_code", None),
        analyst_profile_id=None,
        override_rules=tuple(rules),
        enable_override_trace=True,
    )


def _map_observability_to_dto(
    *,
    observability: StatementOverrideObservability,
    dimension_key: str | None,
) -> StatementOverrideTraceDTO:
    """Map a StatementOverrideObservability entity into a DTO.

    Args:
        observability:
            Domain-level observability summary produced by the
            XBRLOverrideObservabilityService.
        dimension_key:
            Optional dimension key filter provided by the caller. The current
            implementation does not apply additional filtering by dimension
            at the domain layer but surfaces the value on the DTO for future
            evolution.

    Returns:
        StatementOverrideTraceDTO instance.
    """
    # Deterministic ordering: sort metrics by their canonical code.
    sorted_metrics = sorted(
        observability.per_metric_decisions.keys(),
        key=lambda m: m.value,
    )

    decisions: dict[str, OverrideDecisionDTO] = {}
    traces: dict[str, list[OverrideTraceEntryDTO]] = {}

    for metric in sorted_metrics:
        decision: EffectiveOverrideDecisionSummary = observability.per_metric_decisions[metric]
        metric_code = metric.value

        # Effective decision per metric.
        decisions[metric_code] = OverrideDecisionDTO(
            base_metric=metric_code,
            final_metric=decision.final_metric.value if decision.final_metric is not None else None,
            applied_rule_id=(
                str(decision.applied_rule_id)
                if getattr(decision, "applied_rule_id", None) is not None
                else None
            ),
            applied_scope=(
                decision.applied_scope.value if decision.applied_scope is not None else None
            ),
            is_suppression=decision.is_suppression,
        )

        # Per-rule trace for this metric.
        metric_trace: Sequence[OverrideTraceEntry] = observability.per_metric_traces.get(
            metric,
            (),
        )

        trace_dtos: list[OverrideTraceEntryDTO] = []
        for entry in metric_trace:
            trace_dtos.append(
                OverrideTraceEntryDTO(
                    # Domain annotates rule_id as str, tests + DTO want int.
                    # Normalize via int() to satisfy both runtime + mypy.
                    rule_id=int(entry.rule_id),
                    scope=entry.scope.value if entry.scope is not None else None,
                    matched=entry.matched,
                    is_suppression=entry.is_suppression,
                    base_metric=entry.base_metric.value,
                    final_metric=(
                        entry.final_metric.value if entry.final_metric is not None else None
                    ),
                    # Domain field is `match_dimensions`, not `dimensions`.
                    match_dimensions=entry.match_dimensions,
                    # Domain likely annotates these as str | None; DTO wants bool.
                    match_cik=bool(entry.match_cik),
                    match_industry_code=bool(entry.match_industry_code),
                    match_analyst_id=bool(entry.match_analyst_id),
                    priority=entry.priority,
                )
            )

        traces[metric_code] = trace_dtos

    return StatementOverrideTraceDTO(
        cik=observability.cik,
        statement_type=observability.statement_type,
        fiscal_year=observability.fiscal_year,
        fiscal_period=observability.fiscal_period,
        version_sequence=observability.version_sequence,
        suppression_count=observability.suppression_count,
        remap_count=observability.remap_count,
        decisions=decisions,
        traces=traces,
        dimension_key=dimension_key,
    )
