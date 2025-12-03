from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from stacklion_api.application.schemas.dto.edgar_dq import (
    PersistNormalizedFactsResultDTO,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.repositories.edgar_facts_repository import (
    EdgarFactsRepository as EdgarFactsRepositoryProtocol,
)
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)


@dataclass(slots=True)
class PersistNormalizedFactsForStatementRequest:
    """Request parameters for persisting normalized facts for a statement."""

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int


class PersistNormalizedFactsForStatementUseCase:
    """Persist normalized facts for a single statement version.

    Args:
        uow: Unit of work exposing EDGAR statements and normalized facts
            repositories.

    Methods:
        execute: Resolve the target statement identity, flatten the canonical
            statement payload into normalized facts, and replace existing facts
            for that identity with the new set.

    Raises:
        EdgarIngestionError: If the statement identity cannot be resolved or
            if the canonical payload is missing.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        statements_repo_type: type[
            EdgarStatementsRepositoryProtocol
        ] = EdgarStatementsRepositoryProtocol,
        facts_repo_type: type[EdgarFactsRepositoryProtocol] = EdgarFactsRepositoryProtocol,
    ) -> None:
        """Initialize the use case with its dependencies.

        Args:
            uow:
                Unit-of-work providing transactional boundaries.
            statements_repo_type:
                Repository interface/key used to resolve the statements repo.
            facts_repo_type:
                Repository interface/key used to resolve the facts repo.
        """
        self._uow = uow
        self._statements_repo_type = statements_repo_type
        self._facts_repo_type = facts_repo_type

    async def execute(
        self,
        req: PersistNormalizedFactsForStatementRequest,
    ) -> PersistNormalizedFactsResultDTO:
        """Persist normalized facts for a single statement identity."""
        async with self._uow as tx:
            statements_repo: EdgarStatementsRepositoryProtocol = tx.get_repository(
                self._statements_repo_type,
            )
            facts_repo: EdgarFactsRepositoryProtocol = tx.get_repository(
                self._facts_repo_type,
            )

            identity = NormalizedStatementIdentity(
                cik=req.cik.strip(),
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
                version_sequence=req.version_sequence,
            )

            if not identity.cik:
                raise EdgarIngestionError(
                    "CIK must not be empty for fact persistence.",
                    details={"cik": req.cik},
                )

            statement = await self._fetch_statement(statements_repo, identity)

            if statement.normalized_payload is None:
                raise EdgarIngestionError(
                    "Cannot persist facts: statement has no normalized payload.",
                    details={
                        "cik": identity.cik,
                        "statement_type": identity.statement_type.value,
                        "fiscal_year": identity.fiscal_year,
                        "fiscal_period": identity.fiscal_period.value,
                        "version_sequence": identity.version_sequence,
                    },
                )

            facts = self._flatten_payload_to_facts(statement)

            await facts_repo.replace_facts_for_statement(identity=identity, facts=facts)
            await tx.commit()

        return PersistNormalizedFactsResultDTO(
            cik=identity.cik,
            statement_type=identity.statement_type,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period,
            version_sequence=identity.version_sequence,
            facts_persisted=len(facts),
        )

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
            "No statement version found for fact persistence.",
            details={
                "cik": identity.cik,
                "statement_type": identity.statement_type.value,
                "fiscal_year": identity.fiscal_year,
                "fiscal_period": identity.fiscal_period.value,
                "version_sequence": identity.version_sequence,
            },
        )

    @staticmethod
    def _flatten_payload_to_facts(
        statement: EdgarStatementVersion,
    ) -> list[EdgarNormalizedFact]:
        """Flatten a canonical normalized payload into fact entities."""
        payload = statement.normalized_payload
        if payload is None:
            # Should be caught by caller, but fail hard if not.
            raise EdgarIngestionError(
                "Cannot flatten facts: statement has no normalized payload.",
                details={
                    "cik": statement.company.cik,
                    "statement_type": statement.statement_type.value,
                    "fiscal_year": statement.fiscal_year,
                    "fiscal_period": statement.fiscal_period.value,
                    "version_sequence": statement.version_sequence,
                },
            )

        cik = payload.cik
        statement_type = payload.statement_type
        accounting_standard = payload.accounting_standard
        fiscal_year = payload.fiscal_year
        fiscal_period = payload.fiscal_period
        statement_date = payload.statement_date
        version_sequence = payload.source_version_sequence
        currency = payload.currency

        core_metrics: Mapping[str, Decimal] = {m.value: v for m, v in payload.core_metrics.items()}
        extra_metrics: Mapping[str, Decimal] = {k: v for k, v in payload.extra_metrics.items()}

        dimensions: Mapping[str, str] = payload.dimensions
        dimension_key = _build_dimension_key(dimensions)

        facts: list[EdgarNormalizedFact] = []

        def add_fact(metric_code: str, value: Decimal) -> None:
            facts.append(
                EdgarNormalizedFact(
                    cik=cik,
                    statement_type=statement_type,
                    accounting_standard=accounting_standard,
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    statement_date=statement_date,
                    version_sequence=version_sequence,
                    metric_code=metric_code,
                    metric_label=None,
                    unit=currency,
                    period_start=None,
                    period_end=statement_date,
                    value=value,
                    dimensions=dict(dimensions),
                    dimension_key=dimension_key,
                    source_line_item=None,
                ),
            )

        for metric_code, v in core_metrics.items():
            add_fact(metric_code, v)

        for metric_code, v in extra_metrics.items():
            add_fact(metric_code, v)

        return facts


def _build_dimension_key(dimensions: Mapping[str, str]) -> str:
    """Build a stable dimension-key string from a dimensions mapping."""
    if not dimensions:
        return "default"

    parts = [f"{k}={dimensions[k]}" for k in sorted(dimensions.keys())]
    return "|".join(parts)
