# src/stacklion_api/application/use_cases/statements/normalize_xbrl_statement.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Normalize a single EDGAR statement from XBRL.

Purpose:
    Given a specific statement identity and a parsed XBRLDocument, locate the
    corresponding metadata-only EdgarStatementVersion, normalize XBRL facts
    into a canonical statement payload, and update the statement version in
    place with Model A semantics.

Layer:
    application/use_cases/statements
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDocument,
    XBRLUnit,
)
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from stacklion_api.domain.services.edgar_normalization import (
    CanonicalStatementNormalizer,
    EdgarFact,
    NormalizationContext,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizeXBRLStatementRequest:
    """Request parameters for normalizing a single EDGAR statement from XBRL.

    Attributes:
        cik:
            Company Central Index Key (digits only).
        statement_type:
            Type of statement to normalize (income, balance sheet, cash flow).
        fiscal_year:
            Fiscal year of the target statement identity.
        fiscal_period:
            Fiscal period of the target statement identity (e.g., FY, Q1).
        accession_id:
            EDGAR accession identifier for the filing that owns the statement.
        version_sequence:
            Version sequence number for this statement identity.
        xbrl_document:
            Parsed XBRLDocument containing the facts to normalize.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    accession_id: str
    version_sequence: int
    xbrl_document: XBRLDocument


@dataclass(frozen=True)
class NormalizeXBRLStatementResult:
    """Result summary for normalizing a single EDGAR statement.

    Attributes:
        cik:
            Company CIK.
        statement_type:
            Statement type that was normalized.
        fiscal_year:
            Fiscal year of the statement identity.
        fiscal_period:
            Fiscal period of the statement identity.
        accession_id:
            Filing accession identifier.
        version_sequence:
            Version sequence that was updated.
        facts_normalized:
            Number of XBRL facts that contributed to the normalized payload.
        normalized:
            Whether normalization actually occurred. This may be false if the
            statement was already normalized or if no usable facts were found.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    accession_id: str
    version_sequence: int
    facts_normalized: int
    normalized: bool


class NormalizeXBRLStatementUseCase:
    """Normalize a single EDGAR statement version from an XBRLDocument.

    This use case implements Model A semantics:

        * It never creates new statement identities.
        * It locates an existing EdgarStatementVersion for the requested
          (cik, statement_type, fiscal_year, fiscal_period, accession_id,
          version_sequence) identity.
        * If the version is still metadata-only (normalized_payload is None),
          it normalizes XBRL facts into a canonical payload and updates the
          version in place with version_source = "EDGAR_XBRL_NORMALIZED".
        * If the version already has a normalized_payload, the use case is
          idempotent and returns without modification.

    Args:
        uow:
            Unit-of-work used to manage statement persistence.
        statements_repo_type:
            Repository key/interface for resolving the statements repository.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        statements_repo_type: type[EdgarStatementsRepositoryProtocol] = (
            EdgarStatementsRepositoryProtocol
        ),
    ) -> None:
        """Initialize the use case with collaborators.

        Args:
            uow:
                Unit-of-work used to coordinate repository access and commits.
            statements_repo_type:
                Repository key/interface for resolving the statements
                repository from the unit-of-work.
        """
        self._uow = uow
        self._statements_repo_type = statements_repo_type
        self._normalizer = CanonicalStatementNormalizer()

    async def execute(self, req: NormalizeXBRLStatementRequest) -> NormalizeXBRLStatementResult:
        """Execute normalization for a single statement version.

        Args:
            req:
                Parameters describing the target statement identity and the
                XBRLDocument that should be used for normalization.

        Returns:
            A :class:`NormalizeXBRLStatementResult` summarizing the outcome.

        Raises:
            EdgarMappingError:
                If request parameters are invalid (empty CIK, accession_id, or
                non-positive fiscal_year / version_sequence).
            EdgarIngestionError:
                If the corresponding statement version cannot be located or
                if no matching versions exist for the requested identity.
        """
        cik = req.cik.strip()
        accession_id = req.accession_id.strip()

        if not cik:
            raise EdgarMappingError("CIK must not be empty for normalize_xbrl_statement().")
        if not accession_id:
            raise EdgarMappingError(
                "accession_id must not be empty for normalize_xbrl_statement().",
            )
        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for normalize_xbrl_statement().",
            )
        if req.version_sequence <= 0:
            raise EdgarMappingError(
                "version_sequence must be a positive integer for normalize_xbrl_statement().",
            )

        logger.info(
            "edgar.normalize_xbrl_statement.start",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "accession_id": accession_id,
                "version_sequence": req.version_sequence,
            },
        )

        async with self._uow as tx:
            statements_repo: EdgarStatementsRepositoryProtocol = tx.get_repository(
                self._statements_repo_type,
            )

            version = await self._load_target_version(
                statements_repo=statements_repo,
                cik=cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
                accession_id=accession_id,
                version_sequence=req.version_sequence,
            )

            # Idempotency: if already normalized, return without changes.
            if version.normalized_payload is not None:
                logger.info(
                    "edgar.normalize_xbrl_statement.idempotent",
                    extra={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "accession_id": accession_id,
                        "version_sequence": req.version_sequence,
                    },
                )
                return NormalizeXBRLStatementResult(
                    cik=cik,
                    statement_type=req.statement_type,
                    fiscal_year=req.fiscal_year,
                    fiscal_period=req.fiscal_period,
                    accession_id=accession_id,
                    version_sequence=req.version_sequence,
                    facts_normalized=0,
                    normalized=False,
                )

            edgar_facts = self._map_xbrl_to_edgar_facts(
                document=req.xbrl_document,
                statement_version=version,
            )

            if not edgar_facts:
                logger.info(
                    "edgar.normalize_xbrl_statement.no_facts",
                    extra={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "accession_id": accession_id,
                        "version_sequence": req.version_sequence,
                    },
                )
                # We still commit a no-op transaction for consistency.
                await tx.commit()
                return NormalizeXBRLStatementResult(
                    cik=cik,
                    statement_type=req.statement_type,
                    fiscal_year=req.fiscal_year,
                    fiscal_period=req.fiscal_period,
                    accession_id=accession_id,
                    version_sequence=req.version_sequence,
                    facts_normalized=0,
                    normalized=False,
                )

            context = NormalizationContext(
                cik=cik,
                statement_type=version.statement_type,
                accounting_standard=version.accounting_standard,
                statement_date=version.statement_date,
                fiscal_year=version.fiscal_year,
                fiscal_period=version.fiscal_period,
                currency=version.currency,
                accession_id=version.accession_id,
                taxonomy="US_GAAP_MIN_E10A",
                version_sequence=version.version_sequence,
                facts=tuple(edgar_facts),
            )

            normalization_result = self._normalizer.normalize(context)

            updated = EdgarStatementVersion(
                company=version.company,
                filing=version.filing,
                statement_type=version.statement_type,
                accounting_standard=version.accounting_standard,
                statement_date=version.statement_date,
                fiscal_year=version.fiscal_year,
                fiscal_period=version.fiscal_period,
                currency=version.currency,
                is_restated=version.is_restated,
                restatement_reason=version.restatement_reason,
                version_source="EDGAR_XBRL_NORMALIZED",
                version_sequence=version.version_sequence,
                accession_id=version.accession_id,
                filing_date=version.filing_date,
                normalized_payload=normalization_result.payload,
                normalized_payload_version=normalization_result.payload_version,
            )

            await statements_repo.upsert_statement_versions([updated])
            await tx.commit()

        logger.info(
            "edgar.normalize_xbrl_statement.success",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "accession_id": accession_id,
                "version_sequence": req.version_sequence,
                "facts_normalized": len(edgar_facts),
            },
        )

        return NormalizeXBRLStatementResult(
            cik=cik,
            statement_type=req.statement_type,
            fiscal_year=req.fiscal_year,
            fiscal_period=req.fiscal_period,
            accession_id=accession_id,
            version_sequence=req.version_sequence,
            facts_normalized=len(edgar_facts),
            normalized=True,
        )

    async def _load_target_version(
        self,
        *,
        statements_repo: EdgarStatementsRepositoryProtocol,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
        accession_id: str,
        version_sequence: int,
    ) -> EdgarStatementVersion:
        """Load the target statement version for normalization.

        Args:
            statements_repo:
                Repository used to query statement versions.
            cik:
                Company CIK.
            statement_type:
                Statement type for the identity.
            fiscal_year:
                Fiscal year for the identity.
            fiscal_period:
                Fiscal period for the identity.
            accession_id:
                Filing accession identifier.
            version_sequence:
                Version sequence number.

        Returns:
            The matching :class:`EdgarStatementVersion`.

        Raises:
            EdgarIngestionError:
                If no matching version can be found.
        """
        candidates: Sequence[EdgarStatementVersion] = (
            await statements_repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=statement_type,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
            )
        )

        # Filter to the requested accession/version.
        matching = [
            sv
            for sv in candidates
            if sv.accession_id == accession_id and sv.version_sequence == version_sequence
        ]

        if not matching:
            raise EdgarIngestionError(
                "No matching EDGAR statement version for XBRL normalization.",
                details={
                    "cik": cik,
                    "statement_type": statement_type.value,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period.value,
                    "accession_id": accession_id,
                    "version_sequence": version_sequence,
                },
            )

        # In practice there should be exactly one, but we deterministically
        # pick the max version_sequence to be defensive.
        return max(matching, key=lambda v: v.version_sequence)

    @staticmethod
    def _map_xbrl_to_edgar_facts(
        *,
        document: XBRLDocument,
        statement_version: EdgarStatementVersion,
    ) -> list[EdgarFact]:
        """Map XBRL facts into EdgarFact instances for normalization.

        This mapping mirrors the E10-A behavior used in the filing-level
        XBRL processing use case and focuses on:

            * Concept qname (e.g., "us-gaap:Revenues").
            * Statement currency / XBRL unit measure.
            * Period start/end/instant derived from contexts.
            * Decimals hint.
            * Empty dimensions (primary consolidated statements).

        Args:
            document:
                Parsed XBRLDocument.
            statement_version:
                Target statement version for which facts are being prepared.

        Returns:
            List of EdgarFact instances to feed into the normalization engine.
        """
        edgar_facts: list[EdgarFact] = []

        for fact in document.facts:
            ctx: XBRLContext | None = document.contexts.get(fact.context_ref)
            if ctx is None:
                continue

            # Unit mapping: prefer XBRL unit measure, fall back to statement currency.
            unit_str = statement_version.currency
            if fact.unit_ref:
                unit: XBRLUnit | None = document.units.get(fact.unit_ref)
                if unit is not None and unit.measure:
                    measure = unit.measure.strip().upper()
                    unit_str = measure.split(":", 1)[1] if ":" in measure else measure

            period_start = ctx.period.start_date if not ctx.period.is_instant else None
            period_end = ctx.period.end_date if not ctx.period.is_instant else None
            instant_date = ctx.period.instant_date if ctx.period.is_instant else None

            if fact.is_nil:
                # Skip nil facts for E10 normalization.
                continue

            edgar_facts.append(
                EdgarFact(
                    fact_id=fact.id or f"{fact.concept_qname}:{fact.context_ref}",
                    concept=fact.concept_qname,
                    value=fact.raw_value,
                    unit=unit_str,
                    decimals=fact.decimals,
                    period_start=period_start,
                    period_end=period_end,
                    instant_date=instant_date,
                    dimensions={},
                )
            )

        return edgar_facts
