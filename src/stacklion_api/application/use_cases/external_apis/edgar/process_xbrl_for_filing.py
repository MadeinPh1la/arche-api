# src/stacklion_api/application/use_cases/external_apis/edgar/process_xbrl_for_filing.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Process XBRL for an EDGAR filing.

Purpose:
    Given a CIK and accession_id for a filing that has been ingested at the
    metadata level, fetch the associated XBRL document, parse it into a
    domain-level XBRLDocument, normalize facts into a canonical statement
    payload per statement type, attach the payloads to statement versions, and
    persist normalized facts into the fact store.

Layer:
    application/use_cases/external_apis/edgar

Notes:
    - This use case does not create new statement identities; it enriches
      existing metadata-only statement versions produced by the ingestion
      pipeline, using Model A semantics (update in-place).
    - XBRL fetching is performed via the EDGAR ingestion gateway.
    - XML parsing is performed via the XBRLParserGateway adapter.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.persist_normalized_facts_for_statement import (
    PersistNormalizedFactsForStatementUseCase,
)
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.entities.xbrl_document import XBRLContext, XBRLDocument
from stacklion_api.domain.enums.edgar import StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.gateways.edgar_ingestion_gateway import (
    EdgarIngestionGateway,
)
from stacklion_api.domain.interfaces.gateways.xbrl_parser_gateway import (
    XBRLParserGateway,
)
from stacklion_api.domain.interfaces.repositories.edgar_facts_repository import (
    EdgarFactsRepository as EdgarFactsRepositoryProtocol,
)
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
class ProcessXBRLForFilingRequest:
    """Request parameters for processing XBRL for a filing.

    Attributes:
        cik:
            Central Index Key for the filer.
        accession_id:
            EDGAR accession identifier for the filing whose XBRL should be
            processed.
        statement_types:
            Statement types to process. An empty sequence means "all core
            statements" (balance sheet, income statement, cash flow).
    """

    cik: str
    accession_id: str
    statement_types: Sequence[StatementType]


@dataclass(frozen=True)
class ProcessXBRLForFilingResult:
    """Result of processing XBRL for a filing.

    Attributes:
        cik:
            Company CIK.
        accession_id:
            Filing accession identifier.
        statement_types_processed:
            Statement types for which canonical payloads and facts were
            produced.
        facts_persisted:
            Total number of normalized facts persisted across all statements.
    """

    cik: str
    accession_id: str
    statement_types_processed: Sequence[StatementType]
    facts_persisted: int


class ProcessXBRLForFilingUseCase:
    """Process XBRL for an EDGAR filing into canonical payloads and facts.

    Args:
        uow:
            Unit-of-work used to manage statement and fact persistence.
        ingestion_gateway:
            Gateway used to fetch XBRL documents.
        xbrl_parser_gateway:
            Gateway used to parse raw XBRL into XBRLDocument instances.
        statements_repo_type:
            Repository key/interface for resolving the statements repository.
        facts_repo_type:
            Repository key/interface for resolving the facts repository.

    Returns:
        Instances of :class:`ProcessXBRLForFilingResult` from
        :meth:`execute`.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        ingestion_gateway: EdgarIngestionGateway,
        xbrl_parser_gateway: XBRLParserGateway,
        statements_repo_type: type[EdgarStatementsRepositoryProtocol] = (
            EdgarStatementsRepositoryProtocol
        ),
        facts_repo_type: type[EdgarFactsRepositoryProtocol] = EdgarFactsRepositoryProtocol,
    ) -> None:
        """Initialize the use case with collaborators and repository types."""
        self._uow = uow
        self._ingestion_gateway = ingestion_gateway
        self._xbrl_parser_gateway = xbrl_parser_gateway
        self._statements_repo_type = statements_repo_type
        self._facts_repo_type = facts_repo_type
        self._normalizer = CanonicalStatementNormalizer()

    async def execute(self, req: ProcessXBRLForFilingRequest) -> ProcessXBRLForFilingResult:
        """Execute XBRL processing for a single filing.

        Args:
            req:
                Parameters describing the filing and statement types to process.

        Returns:
            ProcessXBRLForFilingResult with summary information.

        Raises:
            EdgarMappingError:
                If the request parameters are invalid (e.g., empty CIK).
            EdgarIngestionError:
                If XBRL cannot be fetched or parsed, or if the corresponding
                statement versions cannot be located.
        """
        cik = req.cik.strip()
        accession_id = req.accession_id.strip()

        if not cik:
            raise EdgarMappingError("CIK must not be empty for process_xbrl_for_filing().")
        if not accession_id:
            raise EdgarMappingError(
                "accession_id must not be empty for process_xbrl_for_filing().",
            )

        logger.info(
            "edgar.process_xbrl_for_filing.start",
            extra={
                "cik": cik,
                "accession_id": accession_id,
                "statement_types": [st.value for st in req.statement_types],
            },
        )

        # 1) Fetch and parse XBRL into a domain-level document.
        document = await self._fetch_and_parse_xbrl(cik=cik, accession_id=accession_id)

        # 2) Normalize and persist within a single transactional boundary.
        result = await self._normalize_and_persist(
            cik=cik,
            accession_id=accession_id,
            requested_types=req.statement_types,
            document=document,
        )

        logger.info(
            "edgar.process_xbrl_for_filing.success",
            extra={
                "cik": cik,
                "accession_id": accession_id,
                "statement_types_processed": [st.value for st in result.statement_types_processed],
                "facts_persisted": result.facts_persisted,
            },
        )
        return result

    async def _fetch_and_parse_xbrl(self, *, cik: str, accession_id: str) -> XBRLDocument:
        """Fetch raw XBRL bytes and parse into an XBRLDocument."""
        xbrl_bytes = await self._ingestion_gateway.fetch_xbrl_for_filing(
            cik=cik,
            accession_id=accession_id,
        )
        document = await self._xbrl_parser_gateway.parse_xbrl(
            accession_id=accession_id,
            content=xbrl_bytes,
        )
        return document

    async def _normalize_and_persist(
        self,
        *,
        cik: str,
        accession_id: str,
        requested_types: Sequence[StatementType],
        document: XBRLDocument,
    ) -> ProcessXBRLForFilingResult:
        """Normalize for each target statement type and persist results."""
        async with self._uow as tx:
            statements_repo: EdgarStatementsRepositoryProtocol = tx.get_repository(
                self._statements_repo_type,
            )
            facts_repo: EdgarFactsRepositoryProtocol = tx.get_repository(self._facts_repo_type)

            target_types = self._resolve_target_statement_types(requested_types=requested_types)
            versions = await self._load_statement_versions(
                statements_repo=statements_repo,
                cik=cik,
                target_types=target_types,
                accession_id=accession_id,
            )
            versions_by_type = self._group_versions_by_accession(
                versions=versions,
                accession_id=accession_id,
                requested_types=requested_types,
                cik=cik,
            )
            (
                updated_versions,
                all_facts,
                processed_types,
                total_facts,
            ) = self._normalize_versions_for_document(
                cik=cik,
                accession_id=accession_id,
                requested_types=requested_types,
                versions_by_type=versions_by_type,
                document=document,
            )

            await self._persist_normalization_results(
                tx=tx,
                statements_repo=statements_repo,
                facts_repo=facts_repo,
                updated_versions=updated_versions,
                all_facts=all_facts,
            )

        return ProcessXBRLForFilingResult(
            cik=cik,
            accession_id=accession_id,
            statement_types_processed=tuple(processed_types),
            facts_persisted=total_facts,
        )

    def _resolve_target_statement_types(
        self,
        *,
        requested_types: Sequence[StatementType],
    ) -> set[StatementType]:
        """Resolve which statement types should be processed."""
        if requested_types:
            return set(requested_types)

        # Core trio; enough for E10-A semantics.
        return {
            StatementType.BALANCE_SHEET,
            StatementType.INCOME_STATEMENT,
            StatementType.CASH_FLOW_STATEMENT,
        }

    async def _load_statement_versions(
        self,
        *,
        statements_repo: EdgarStatementsRepositoryProtocol,
        cik: str,
        target_types: set[StatementType],
        accession_id: str,
    ) -> list[EdgarStatementVersion]:
        """Load candidate statement versions for the given company and types."""
        versions: list[EdgarStatementVersion] = []

        for st in target_types:
            versions_for_type = await statements_repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=st,
                fiscal_year=0,
                fiscal_period=None,
            )
            versions.extend(versions_for_type)

        if not versions:
            raise EdgarIngestionError(
                "No EDGAR statement versions found for XBRL processing.",
                details={"cik": cik, "accession_id": accession_id},
            )

        return versions

    def _group_versions_by_accession(
        self,
        *,
        versions: Sequence[EdgarStatementVersion],
        accession_id: str,
        requested_types: Sequence[StatementType],
        cik: str,
    ) -> dict[StatementType, list[EdgarStatementVersion]]:
        """Group statement versions by type, filtered to the target accession."""
        versions_by_type: dict[StatementType, list[EdgarStatementVersion]] = {}

        for sv in versions:
            if sv.accession_id != accession_id:
                continue
            versions_by_type.setdefault(sv.statement_type, []).append(sv)

        if not versions_by_type:
            raise EdgarIngestionError(
                "No matching EDGAR statement versions for XBRL processing.",
                details={
                    "cik": cik,
                    "accession_id": accession_id,
                    "statement_types": [st.value for st in requested_types],
                },
            )

        return versions_by_type

    def _normalize_versions_for_document(
        self,
        *,
        cik: str,
        accession_id: str,
        requested_types: Sequence[StatementType],
        versions_by_type: dict[StatementType, list[EdgarStatementVersion]],
        document: XBRLDocument,
    ) -> tuple[
        list[EdgarStatementVersion],
        list[tuple[NormalizedStatementIdentity, list[EdgarNormalizedFact]]],
        list[StatementType],
        int,
    ]:
        """Normalize each statement type and build the facts payloads."""
        updated_versions: list[EdgarStatementVersion] = []
        all_facts: list[tuple[NormalizedStatementIdentity, list[EdgarNormalizedFact]]] = []
        processed_types: list[StatementType] = []
        total_facts = 0

        for statement_type, st_versions in versions_by_type.items():
            result = self._normalize_for_statement_type(
                cik=cik,
                accession_id=accession_id,
                statement_type=statement_type,
                statement_versions=st_versions,
                document=document,
            )
            if result is None:
                continue

            updated, identity, facts = result
            updated_versions.append(updated)
            all_facts.append((identity, facts))
            processed_types.append(statement_type)
            total_facts += len(facts)

        if not updated_versions:
            raise EdgarIngestionError(
                "No statement versions were normalized from XBRL.",
                details={"cik": cik, "accession_id": accession_id},
            )

        return updated_versions, all_facts, processed_types, total_facts

    async def _persist_normalization_results(
        self,
        *,
        tx: Any,
        statements_repo: EdgarStatementsRepositoryProtocol,
        facts_repo: EdgarFactsRepositoryProtocol,
        updated_versions: Sequence[EdgarStatementVersion],
        all_facts: Sequence[tuple[NormalizedStatementIdentity, list[EdgarNormalizedFact]]],
    ) -> None:
        """Persist normalized statement versions and their facts, then commit."""
        await statements_repo.upsert_statement_versions(list(updated_versions))
        for identity, facts in all_facts:
            await facts_repo.replace_facts_for_statement(identity=identity, facts=facts)
        await tx.commit()

    def _normalize_for_statement_type(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type: StatementType,
        statement_versions: Sequence[EdgarStatementVersion],
        document: XBRLDocument,
    ) -> (
        tuple[EdgarStatementVersion, NormalizedStatementIdentity, list[EdgarNormalizedFact]] | None
    ):
        """Normalize XBRL facts for a single statement type.

        Returns:
            Tuple of (updated_statement_version, identity, facts) or None if
            there is nothing to update for this statement type.
        """
        if not statement_versions:
            return None

        latest = max(statement_versions, key=lambda v: v.version_sequence)
        if latest.normalized_payload is not None:
            # Already normalized; preserve idempotency.
            return None

        edgar_facts = self._map_xbrl_to_edgar_facts(
            document=document,
            statement_version=latest,
        )

        if not edgar_facts:
            logger.info(
                "edgar.process_xbrl_for_filing.no_facts_for_statement",
                extra={
                    "cik": cik,
                    "accession_id": accession_id,
                    "statement_type": latest.statement_type.value,
                },
            )
            return None

        context = NormalizationContext(
            cik=cik,
            statement_type=latest.statement_type,
            accounting_standard=latest.accounting_standard,
            statement_date=latest.statement_date,
            fiscal_year=latest.fiscal_year,
            fiscal_period=latest.fiscal_period,
            currency=latest.currency,
            accession_id=latest.accession_id,
            taxonomy="US_GAAP_MIN_E10A",
            version_sequence=latest.version_sequence,
            facts=tuple(edgar_facts),
        )

        normalization_result = self._normalizer.normalize(context)

        updated = EdgarStatementVersion(
            company=latest.company,
            filing=latest.filing,
            statement_type=latest.statement_type,
            accounting_standard=latest.accounting_standard,
            statement_date=latest.statement_date,
            fiscal_year=latest.fiscal_year,
            fiscal_period=latest.fiscal_period,
            currency=latest.currency,
            is_restated=latest.is_restated,
            restatement_reason=latest.restatement_reason,
            version_source="EDGAR_XBRL_NORMALIZED",
            version_sequence=latest.version_sequence,
            accession_id=latest.accession_id,
            filing_date=latest.filing_date,
            normalized_payload=normalization_result.payload,
            normalized_payload_version=normalization_result.payload_version,
        )

        identity = NormalizedStatementIdentity(
            cik=updated.company.cik,
            statement_type=updated.statement_type,
            fiscal_year=updated.fiscal_year,
            fiscal_period=updated.fiscal_period,
            version_sequence=updated.version_sequence,
        )

        facts = PersistNormalizedFactsForStatementUseCase._flatten_payload_to_facts(updated)

        return updated, identity, facts

    @staticmethod
    def _map_xbrl_to_edgar_facts(
        *,
        document: XBRLDocument,
        statement_version: EdgarStatementVersion,
    ) -> list[EdgarFact]:
        """Map XBRL facts into EdgarFact instances for normalization.

        This mapping is intentionally minimal in E10-A and focuses on:

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
                unit = document.units.get(fact.unit_ref)
                if unit is not None and unit.measure:
                    measure = unit.measure.strip().upper()
                    unit_str = measure.split(":", 1)[1] if ":" in measure else measure

            period_start = ctx.period.start_date if not ctx.period.is_instant else None
            period_end = ctx.period.end_date if not ctx.period.is_instant else None
            instant_date = ctx.period.instant_date if ctx.period.is_instant else None

            if fact.is_nil:
                # Skip nil facts for E10-A normalization.
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
