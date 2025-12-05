# src/stacklion_api/application/use_cases/statements/normalize_xbrl_statement.py
# SPDX-License-Identifier: MIT
"""Use case: Normalize an XBRLDocument into a canonical statement payload.

Attach it to an existing EdgarStatementVersion.

Layer:
    application/use_cases/statements
"""

from __future__ import annotations

from dataclasses import dataclass

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.entities.xbrl_document import XBRLDocument
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.domain.services.edgar_normalization import (
    CanonicalStatementNormalizer,
    EdgarFact,
    NormalizationContext,
)
from stacklion_api.domain.services.gaap_taxonomy import build_minimal_gaap_taxonomy


@dataclass(frozen=True)
class NormalizeXBRLStatementRequest:
    """Request parameters for normalizing a single XBRL-backed statement.

    Attributes:
        cik:
            Company CIK for the statement identity.
        statement_type:
            Statement type (income, balance sheet, cash flow, etc.).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2).
        accession_id:
            EDGAR accession identifier for the filing.
        version_sequence:
            Statement version sequence to attach the normalized payload to.
        xbrl_document:
            Parsed :class:`XBRLDocument` providing contexts, units, and facts.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    accession_id: str
    version_sequence: int
    xbrl_document: XBRLDocument


class NormalizeXBRLStatementUseCase:
    """Normalize XBRL facts into a canonical statement payload for one version.

    Args:
        uow:
            Application unit of work used to resolve repositories and manage
            the normalization transaction.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the normalization use case.

        Args:
            uow:
                Unit-of-work providing access to the statements repository.
        """
        self._uow = uow
        self._taxonomy = build_minimal_gaap_taxonomy()
        self._normalizer = CanonicalStatementNormalizer()

    async def execute(self, req: NormalizeXBRLStatementRequest) -> None:
        """Execute normalization for the requested statement identity.

        Args:
            req:
                Request parameters identifying the target statement version and
                providing its XBRL document.

        Raises:
            EdgarIngestionError:
                If the statement version cannot be found or XBRL cannot be
                normalized safely.
        """
        async with self._uow as tx:
            repo: EdgarStatementsRepository = tx.get_repository(EdgarStatementsRepository)

            versions = await repo.list_statement_versions_for_company(
                cik=req.cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
            )

            target: EdgarStatementVersion | None = None
            for version in versions:
                if (
                    version.version_sequence == req.version_sequence
                    and version.accession_id == req.accession_id
                ):
                    target = version
                    break

            if target is None:
                raise EdgarIngestionError(
                    "Target statement version not found for XBRL normalization.",
                    details={
                        "cik": req.cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "accession_id": req.accession_id,
                        "version_sequence": req.version_sequence,
                    },
                )

            edgar_facts = self._map_xbrl_facts_to_edgar_facts(
                document=req.xbrl_document,
                target=target,
            )

            if not edgar_facts:
                raise EdgarIngestionError(
                    "No usable XBRL facts found for statement normalization.",
                    details={
                        "cik": req.cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                    },
                )

            context = NormalizationContext(
                cik=req.cik,
                statement_type=target.statement_type,
                accounting_standard=target.accounting_standard,
                statement_date=target.statement_date,
                fiscal_year=target.fiscal_year,
                fiscal_period=target.fiscal_period,
                currency=target.currency,
                accession_id=target.accession_id,
                taxonomy="US_GAAP_MIN_E10A",
                version_sequence=target.version_sequence,
                facts=tuple(edgar_facts),
            )

            result = self._normalizer.normalize(context)

            updated = EdgarStatementVersion(
                company=target.company,
                filing=target.filing,
                statement_type=target.statement_type,
                accounting_standard=target.accounting_standard,
                statement_date=target.statement_date,
                fiscal_year=target.fiscal_year,
                fiscal_period=target.fiscal_period,
                currency=target.currency,
                is_restated=target.is_restated,
                restatement_reason=target.restatement_reason,
                version_source="EDGAR_XBRL_NORMALIZED",
                version_sequence=target.version_sequence,
                accession_id=target.accession_id,
                filing_date=target.filing_date,
                normalized_payload=result.payload,
                normalized_payload_version=result.payload_version,
            )

            await repo.upsert_statement_versions([updated])
            await tx.commit()

    @staticmethod
    def _map_xbrl_facts_to_edgar_facts(
        *,
        document: XBRLDocument,
        target: EdgarStatementVersion,
    ) -> list[EdgarFact]:
        """Map XBRL facts from a document into :class:`EdgarFact` records.

        Args:
            document:
                Parsed :class:`XBRLDocument` providing contexts, units, and
                facts.
            target:
                Target :class:`EdgarStatementVersion` for which facts are being
                normalized.

        Returns:
            List of :class:`EdgarFact` instances suitable for the normalization
            engine.
        """
        edgar_facts: list[EdgarFact] = []

        for fact in document.facts:
            ctx = document.contexts.get(fact.context_ref)
            if ctx is None:
                continue

            if fact.is_nil:
                # Skip nil facts; they do not contribute numeric information.
                continue

            unit_code = target.currency
            if fact.unit_ref:
                unit = document.units.get(fact.unit_ref)
                if unit is not None and unit.measure:
                    measure = unit.measure.strip().upper()
                    unit_code = measure.split(":", 1)[1] if ":" in measure else measure

            period_start = ctx.period.start_date if not ctx.period.is_instant else None
            period_end = ctx.period.end_date if not ctx.period.is_instant else None
            instant = ctx.period.instant_date if ctx.period.is_instant else None

            edgar_facts.append(
                EdgarFact(
                    fact_id=fact.id or f"{fact.concept_qname}:{fact.context_ref}",
                    concept=fact.concept_qname,
                    value=fact.raw_value,
                    unit=unit_code,
                    decimals=fact.decimals,
                    period_start=period_start,
                    period_end=period_end,
                    instant_date=instant,
                    dimensions={},
                )
            )

        return edgar_facts
