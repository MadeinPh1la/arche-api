# src/stacklion_api/adapters/presenters/edgar_dq_presenter.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Presenters for EDGAR Data Quality (DQ) use-cases."""

from __future__ import annotations

from collections.abc import Iterable

from stacklion_api.adapters.schemas.http.edgar_dq_schemas import (
    DQAnomalyHTTP,
    FactQualityHTTP,
    NormalizedFactHTTP,
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import SuccessEnvelope
from stacklion_api.application.schemas.dto.edgar_dq import (
    DQAnomalyDTO,
    FactQualityDTO,
    NormalizedFactDTO,
    RunStatementDQResultDTO,
    StatementDQOverlayDTO,
)


def _present_normalized_fact(fact: NormalizedFactDTO) -> NormalizedFactHTTP:
    """Map NormalizedFactDTO → NormalizedFactHTTP."""
    return NormalizedFactHTTP(
        cik=fact.cik,
        statement_type=fact.statement_type.value,
        accounting_standard=fact.accounting_standard.value,
        fiscal_year=fact.fiscal_year,
        fiscal_period=fact.fiscal_period.value,
        statement_date=fact.statement_date,
        version_sequence=fact.version_sequence,
        metric_code=fact.metric_code,
        metric_label=fact.metric_label,
        unit=fact.unit,
        period_start=fact.period_start,
        period_end=fact.period_end,
        value=fact.value,
        dimension_key=fact.dimension_key,
        dimensions=fact.dimensions,
        source_line_item=fact.source_line_item,
    )


def _present_fact_quality(fq: FactQualityDTO) -> FactQualityHTTP:
    """Map FactQualityDTO → FactQualityHTTP."""
    return FactQualityHTTP(
        cik=fq.cik,
        statement_type=fq.statement_type.value,
        fiscal_year=fq.fiscal_year,
        fiscal_period=fq.fiscal_period.value,
        version_sequence=fq.version_sequence,
        metric_code=fq.metric_code,
        dimension_key=fq.dimension_key,
        severity=fq.severity,
        is_present=fq.is_present,
        is_non_negative=fq.is_non_negative,
        is_consistent_with_history=fq.is_consistent_with_history,
        has_known_issue=fq.has_known_issue,
        details=fq.details,
    )


def _present_anomaly(anomaly: DQAnomalyDTO) -> DQAnomalyHTTP:
    """Map DQAnomalyDTO → DQAnomalyHTTP."""
    return DQAnomalyHTTP(
        dq_run_id=anomaly.dq_run_id,
        metric_code=anomaly.metric_code,
        dimension_key=anomaly.dimension_key,
        rule_code=anomaly.rule_code,
        severity=anomaly.severity,
        message=anomaly.message,
        details=anomaly.details,
    )


def _present_facts_sorted(
    facts: Iterable[NormalizedFactDTO],
) -> list[NormalizedFactHTTP]:
    """Present facts with deterministic ordering (metric_code, dimension_key)."""
    sorted_facts = sorted(
        facts,
        key=lambda f: (f.metric_code, f.dimension_key),
    )
    return [_present_normalized_fact(f) for f in sorted_facts]


def present_run_statement_dq(
    result: RunStatementDQResultDTO,
) -> SuccessEnvelope[RunStatementDQResultHTTP]:
    """Present the result of a RunStatementDQUseCase."""
    http_result = RunStatementDQResultHTTP(
        dq_run_id=result.dq_run_id,
        cik=result.cik,
        statement_type=result.statement_type.value,
        fiscal_year=result.fiscal_year,
        fiscal_period=result.fiscal_period.value,
        version_sequence=result.version_sequence,
        rule_set_version=result.rule_set_version,
        scope_type=result.scope_type,
        history_lookback=result.history_lookback,
        executed_at=result.executed_at,
        facts_evaluated=result.facts_evaluated,
        anomaly_count=result.anomaly_count,
        max_severity=result.max_severity,
    )
    return SuccessEnvelope(data=http_result)


def present_statement_dq_overlay(
    overlay: StatementDQOverlayDTO,
) -> SuccessEnvelope[StatementDQOverlayHTTP]:
    """Present a statement + DQ overlay."""
    facts_http = _present_facts_sorted(overlay.facts)
    fact_quality_http = [_present_fact_quality(fq) for fq in overlay.fact_quality]
    anomalies_http = [_present_anomaly(a) for a in overlay.anomalies]

    http_overlay = StatementDQOverlayHTTP(
        cik=overlay.cik,
        statement_type=overlay.statement_type.value,
        fiscal_year=overlay.fiscal_year,
        fiscal_period=overlay.fiscal_period.value,
        version_sequence=overlay.version_sequence,
        accounting_standard=overlay.accounting_standard.value,
        statement_date=overlay.statement_date,
        currency=overlay.currency,
        dq_run_id=overlay.dq_run_id,
        dq_rule_set_version=overlay.dq_rule_set_version,
        dq_executed_at=overlay.dq_executed_at,
        max_severity=overlay.max_severity,
        facts=facts_http,
        fact_quality=fact_quality_http,
        anomalies=anomalies_http,
    )

    return SuccessEnvelope(data=http_overlay)
