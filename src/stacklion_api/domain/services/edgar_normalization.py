# src/stacklion_api/domain/services/edgar_normalization.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR canonical statement normalization engine.

Purpose:
    Provide a deterministic, provider-agnostic normalization engine that turns
    EDGAR-style facts into a CanonicalStatementPayload suitable for downstream
    modeling and analytics.

    Phase E10-B introduces GAAP linkbase-aware structural normalization at the
    XBRL layer (statement layout, labels, section ordering). This module
    remains focused on canonical metric resolution and payload construction;
    it assumes that any linkbase-driven ordering or labeling has already been
    applied upstream when shaping the input facts.

    Phase E10-C extends the normalization context with optional metadata
    required by the XBRL mapping override engine (industry, analyst profile,
    and override rules) and integrates a deterministic override evaluation
    step into metric resolution.

Layer:
    domain

Design:
    - Pure domain: no HTTP, no ORM, no transport dependencies.
    - Numeric values use Decimal internally; callers serialize to strings.
    - All amounts are in full reporting units (unit_multiplier == 0).
    - Deterministic behavior: no randomness, no reliance on iteration order.
    - Graceful degradation:
        * Missing metrics are omitted and surfaced via warnings.
        * Ambiguous or invalid facts raise domain-level errors.

Notes:
    - This module intentionally does not know about raw EDGAR JSON; upstream
      layers are responsible for mapping SEC payloads into EdgarFact instances.
    - The canonical metric taxonomy is intentionally small (Tier 1) and can be
      extended in later phases without breaking existing behavior, as long as
      canonical semantics are preserved.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum, auto
from typing import TYPE_CHECKING, Final

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError
from stacklion_api.domain.services.xbrl_mapping_overrides import (
    XBRLMappingOverrideEngine,
)

if TYPE_CHECKING:
    from stacklion_api.domain.services.xbrl_mapping_overrides import MappingOverrideRule

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Version identifier for normalized payloads produced by this engine.
NORMALIZED_PAYLOAD_VERSION: Final[str] = "v1"


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgarFact:
    """Domain-level representation of a single EDGAR/XBRL fact.

    This is a provider-normalized shape that upstream adapters should map SEC
    payloads into before invoking the canonicalization engine.

    Attributes:
        fact_id:
            Stable identifier for the fact (e.g., a composite of concept and
            contextRef or a database identifier). Used for traceability.
        concept:
            XBRL concept name (e.g., "us-gaap:Revenues").
        value:
            Raw numeric value as provided by the source. Upstream mappers may
            normalize this into a string that is safe to parse as Decimal.
        unit:
            Unit identifier (e.g., "USD", "shares", "pure").
        decimals:
            Optional EDGAR/XBRL decimals attribute. When provided, it indicates
            the number of decimal places of precision or rounding. The engine
            treats this as a precision hint and does not apply additional
            scaling beyond the reported value.
        period_start:
            Start date of the reporting period (for duration facts), if known.
        period_end:
            End date of the reporting period (for duration facts), if known.
        instant_date:
            Instant date for instant facts (e.g., balance sheet), if applicable.
        dimensions:
            Dimensional qualifiers for the fact (e.g., consolidation, segment).
            E6-F focuses on primary consolidated statements; upstream mapping
            should prefer consolidated contexts for normalization.
    """

    fact_id: str
    concept: str
    value: str
    unit: str
    decimals: int | None
    period_start: date | None
    period_end: date | None
    instant_date: date | None
    dimensions: Mapping[str, str]


class MetricConfidence(Enum):
    """Confidence level for a canonical metric mapping."""

    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


@dataclass(frozen=True)
class CanonicalMetricRecord:
    """Resolved canonical metric value and provenance.

    Attributes:
        metric:
            Canonical metric identifier.
        value:
            Normalized Decimal value for the metric in full reporting units.
        unit:
            Canonical unit string (e.g., "USD", "SHARE").
        confidence:
            Confidence level for the mapping (HIGH, MEDIUM, LOW).
        source_fact_ids:
            Fact identifiers that contributed to this metric (usually 1).

    Notes:
        Phase E10-C keeps this record focused on value + provenance. Override
        metadata (scope, rule id, debug trace) is handled by the override
        engine and may be surfaced via a separate summary structure in a
        later micro-phase.
    """

    metric: CanonicalStatementMetric
    value: Decimal
    unit: str
    confidence: MetricConfidence
    source_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class NormalizationContext:
    """Input context for canonical statement normalization.

    Attributes:
        cik:
            Company CIK for which this statement is being normalized.
        statement_type:
            Type of statement (income, balance sheet, cash flow, etc.).
        accounting_standard:
            Accounting standard (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date for the statement.
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2).
        currency:
            ISO currency code for the reporting currency (e.g., "USD").
        accession_id:
            EDGAR accession ID for the underlying filing.
        taxonomy:
            Textual identifier of the taxonomy (e.g., "US_GAAP_2024").
        version_sequence:
            Sequence number from the underlying statement version.
        facts:
            Sequence of EDGAR facts relevant to this statement. Upstream
            mapping is responsible for supplying facts filtered to the
            appropriate company and filing and for applying any GAAP
            linkbase-driven ordering or labeling when building higher-level
            statement views.
        industry_code:
            Optional industry or sector classification for the company.
            Introduced in Phase E10-C to support industry-scoped overrides.
        analyst_profile_id:
            Optional analyst or configuration profile identifier for
            analyst-scoped overrides.
        override_rules:
            Optional override rules to be considered by the XBRL mapping
            override engine. When empty, no override evaluation is performed.
        enable_override_trace:
            When True and override_rules are provided, the override engine
            will produce a structured trace. The normalizer does not persist
            or log this trace; callers are responsible for any side effects.
    """

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    accession_id: str
    taxonomy: str
    version_sequence: int
    facts: Sequence[EdgarFact]
    industry_code: str | None = None
    analyst_profile_id: str | None = None
    override_rules: Sequence[MappingOverrideRule] = ()
    enable_override_trace: bool = False


@dataclass(frozen=True)
class NormalizationResult:
    """Result of canonical statement normalization.

    Attributes:
        payload:
            CanonicalStatementPayload produced by the engine.
        payload_version:
            Version identifier for the normalization algorithm and payload
            schema. For this engine, this will be NORMALIZED_PAYLOAD_VERSION.
        metric_records:
            Mapping of canonical metrics to their resolved records, including
            confidence and provenance.
        warnings:
            Human-readable warnings about partial mappings, missing metrics,
            or non-fatal anomalies. Intended for logging and diagnostics.

    Notes:
        Override metadata and debug traces are handled by the separate
        XBRLMappingOverrideEngine in Phase E10-C and are not yet surfaced
        through this result type. This preserves compatibility for callers
        relying on the E6/E9 payload contract.
    """

    payload: CanonicalStatementPayload
    payload_version: str
    metric_records: Mapping[CanonicalStatementMetric, CanonicalMetricRecord]
    warnings: tuple[str, ...]


class EdgarNormalizationError(EdgarMappingError):
    """Raised when EDGAR facts cannot be normalized safely."""


# ---------------------------------------------------------------------------
# Canonical metric registry (Tier 1)
# ---------------------------------------------------------------------------

_CANONICAL_METRIC_REGISTRY: Mapping[CanonicalStatementMetric, tuple[str, ...]] = {
    # Income statement
    CanonicalStatementMetric.REVENUE: (
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
        "us-gaap:RevenuesNetOfInterestExpense",
    ),
    CanonicalStatementMetric.NET_INCOME: (
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
    ),
    CanonicalStatementMetric.OPERATING_INCOME: ("us-gaap:OperatingIncomeLoss",),
    CanonicalStatementMetric.BASIC_EPS: ("us-gaap:EarningsPerShareBasic",),
    CanonicalStatementMetric.DILUTED_EPS: ("us-gaap:EarningsPerShareDiluted",),
    CanonicalStatementMetric.WEIGHTED_AVERAGE_SHARES_DILUTED: (
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
    # Balance sheet
    CanonicalStatementMetric.TOTAL_ASSETS: ("us-gaap:Assets",),
    CanonicalStatementMetric.TOTAL_LIABILITIES: ("us-gaap:Liabilities",),
    CanonicalStatementMetric.TOTAL_EQUITY: (
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "us-gaap:Equity",
    ),
    CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: (
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
    ),
    # Cash flow
    CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES: (
        "us-gaap:NetCashProvidedByUsedInInvestingActivities",
        "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ),
    CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES: (
        "us-gaap:NetCashProvidedByUsedInFinancingActivities",
        "us-gaap:NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ),
    CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: (
        "us-gaap:CashAndCashEquivalentsPeriodIncreaseDecrease",
    ),
}


# ---------------------------------------------------------------------------
# Engine implementation
# ---------------------------------------------------------------------------


class CanonicalStatementNormalizer:
    """Canonical EDGAR statement normalization engine."""

    def __init__(
        self,
        *,
        payload_version: str = NORMALIZED_PAYLOAD_VERSION,
        override_engine: XBRLMappingOverrideEngine | None = None,
    ) -> None:
        """Initialize the normalizer.

        Args:
            payload_version:
                Version string to stamp onto the NormalizationResult. This
                allows callers to override the version identifier in tests or
                future engine variants.
            override_engine:
                Optional override engine used in Phase E10-C to apply
                XBRL mapping overrides. When None, override evaluation is
                disabled even if override rules are provided.
        """
        self._payload_version = payload_version
        self._override_engine = override_engine

    def normalize(self, context: NormalizationContext) -> NormalizationResult:
        """Normalize EDGAR facts into a canonical statement payload."""
        _validate_context(context)

        metric_records: dict[CanonicalStatementMetric, CanonicalMetricRecord] = {}
        warnings: list[str] = []

        # Pre-index facts by concept for deterministic lookup.
        facts_by_concept: dict[str, list[EdgarFact]] = defaultdict(list)
        for fact in context.facts:
            facts_by_concept[fact.concept].append(fact)

        for registry_metric, concepts in _CANONICAL_METRIC_REGISTRY.items():
            record, warning = self._resolve_metric(
                registry_metric=registry_metric,
                concepts=concepts,
                context=context,
                facts_by_concept=facts_by_concept,
            )
            if record is not None:
                # Use the record's metric as the key to allow override-based
                # remapping between canonical metrics.
                metric_records[record.metric] = record
            if warning is not None:
                warnings.append(warning)

        payload = CanonicalStatementPayload(
            cik=context.cik,
            statement_type=context.statement_type,
            accounting_standard=context.accounting_standard,
            statement_date=context.statement_date,
            fiscal_year=context.fiscal_year,
            fiscal_period=context.fiscal_period,
            currency=context.currency,
            unit_multiplier=0,
            core_metrics={m: r.value for m, r in metric_records.items()},
            extra_metrics={},
            dimensions={"consolidation": "CONSOLIDATED"},
            source_accession_id=context.accession_id,
            source_taxonomy=context.taxonomy,
            source_version_sequence=context.version_sequence,
        )

        return NormalizationResult(
            payload=payload,
            payload_version=self._payload_version,
            metric_records=metric_records,
            warnings=tuple(warnings),
        )

    def _resolve_metric(
        self,
        *,
        registry_metric: CanonicalStatementMetric,
        concepts: Sequence[str],
        context: NormalizationContext,
        facts_by_concept: Mapping[str, Sequence[EdgarFact]],
    ) -> tuple[CanonicalMetricRecord | None, str | None]:
        """Resolve a single canonical metric from the available facts."""
        for concept in concepts:
            candidates = list(facts_by_concept.get(concept, ()))
            if not candidates:
                continue

            # Prefer facts matching the reporting currency when possible.
            currency_matches = [
                f for f in candidates if f.unit.upper().strip() == context.currency.upper().strip()
            ]
            if currency_matches:
                candidates = currency_matches

            # If multiple facts remain, select deterministically by
            # (period_end or instant_date, fact_id).
            def _sort_key(fact: EdgarFact) -> tuple[date | None, str]:
                ref_date = fact.period_end or fact.instant_date
                return (ref_date, fact.fact_id)

            candidates.sort(key=_sort_key)

            chosen = candidates[-1]  # Most recent / highest fact_id.
            try:
                value = _parse_decimal(chosen.value, chosen.decimals)
            except EdgarNormalizationError as exc:
                raise EdgarNormalizationError(
                    "Failed to parse numeric value for canonical metric.",
                    details={
                        "metric": registry_metric.name,
                        "concept": concept,
                        "fact_id": chosen.fact_id,
                        "value": chosen.value,
                        "error": str(exc),
                    },
                ) from exc

            # Apply override engine, if configured and rules present.
            effective_metric = registry_metric
            if self._override_engine is not None and context.override_rules:
                decision, _trace = self._override_engine.apply(
                    concept=concept,
                    taxonomy=context.taxonomy,
                    fact_dimensions=chosen.dimensions,
                    cik=context.cik,
                    industry_code=context.industry_code,
                    analyst_id=context.analyst_profile_id,
                    base_metric=registry_metric,
                    rules=context.override_rules,
                    debug=context.enable_override_trace,
                )

                if decision.final_metric is None:
                    warning = (
                        f"canonical metric {registry_metric.name} suppressed by override; "
                        f"scope={decision.applied_scope.name if decision.applied_scope else 'NONE'}, "
                        f"rule_id={decision.applied_rule_id}"
                    )
                    return None, warning

                effective_metric = decision.final_metric

            record = CanonicalMetricRecord(
                metric=effective_metric,
                value=value,
                unit=_canonicalize_unit(chosen.unit),
                confidence=MetricConfidence.HIGH,
                source_fact_ids=(chosen.fact_id,),
            )
            return record, None

        # No candidate facts found for any concept for this metric.
        warning = (
            f"canonical metric {registry_metric.name} could not be resolved; "
            "no candidate facts found for registered concepts."
        )
        return None, warning


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_context(context: NormalizationContext) -> None:
    """Validate the normalization context at the domain level."""
    if not context.cik or not context.cik.strip():
        raise EdgarNormalizationError("cik must be a non-empty string.")

    if not context.currency or not context.currency.strip():
        raise EdgarNormalizationError("currency must be a non-empty ISO code.")

    if context.fiscal_year <= 0:
        raise EdgarNormalizationError(f"fiscal_year must be positive; got {context.fiscal_year}")

    if not context.taxonomy or not context.taxonomy.strip():
        raise EdgarNormalizationError("taxonomy must be a non-empty string.")

    if context.version_sequence <= 0:
        raise EdgarNormalizationError(
            f"version_sequence must be positive; got {context.version_sequence}"
        )


def _parse_decimal(value: str, decimals: int | None) -> Decimal:
    """Parse a numeric string into a Decimal with deterministic rules."""
    try:
        dec = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise EdgarNormalizationError(
            "Value could not be parsed as Decimal.",
            details={"value": value},
        ) from exc

    if decimals is not None and decimals >= 0:
        quant = Decimal("1").scaleb(-decimals)
        dec = dec.quantize(quant)

    return dec


def _canonicalize_unit(unit: str) -> str:
    """Canonicalize a unit string into a stable identifier."""
    cleaned = unit.strip().upper()
    if cleaned in {"USD", "US DOLLAR", "US$", "$"}:
        return "USD"
    if cleaned in {"SHARES", "SHARE"}:
        return "SHARE"
    if cleaned in {"PURE"}:
        return "RATIO"

    return cleaned


__all__ = [
    "EdgarFact",
    "MetricConfidence",
    "CanonicalMetricRecord",
    "NormalizationContext",
    "NormalizationResult",
    "EdgarNormalizationError",
    "CanonicalStatementNormalizer",
    "NORMALIZED_PAYLOAD_VERSION",
]
