# Copyright (c)
# SPDX-License-Identifier: MIT
"""Presenters for reconciliation HTTP responses.

Purpose:
    Transform application-layer reconciliation DTOs into stable HTTP
    response envelopes and schemas.

Layer:
    adapters/presenters
"""

from __future__ import annotations

from typing import Any

from arche_api.adapters.schemas.http.envelopes import PaginatedEnvelope, SuccessEnvelope
from arche_api.adapters.schemas.http.reconciliation_schemas import (
    ReconciliationResultHTTP,
    ReconciliationSummaryBucketHTTP,
    RunReconciliationResponseHTTP,
)
from arche_api.application.schemas.dto.reconciliation import (
    GetReconciliationLedgerResponseDTO,
    GetReconciliationSummaryResponseDTO,
    RunReconciliationResponseDTO,
)


def present_run_reconciliation(
    dto: RunReconciliationResponseDTO,
) -> SuccessEnvelope[RunReconciliationResponseHTTP]:
    """Present a reconciliation run response as a success envelope.

    Args:
        dto: Application DTO containing the run id, timestamp, and results.

    Returns:
        SuccessEnvelope containing a RunReconciliationResponseHTTP payload.
    """
    data = RunReconciliationResponseHTTP(
        reconciliation_run_id=dto.reconciliation_run_id,
        executed_at=dto.executed_at,
        results=[_present_result(r) for r in dto.results],
    )
    return SuccessEnvelope(data=data)


def present_reconciliation_ledger(
    dto: GetReconciliationLedgerResponseDTO,
    *,
    page: int,
    page_size: int,
) -> PaginatedEnvelope[ReconciliationResultHTTP]:
    """Present a reconciliation ledger response as a paginated envelope.

    Notes:
        The underlying repository orders ledger entries deterministically; this
        presenter preserves that ordering.

    Args:
        dto: Application DTO containing ordered ledger entries.
        page: 1-based page index requested by the client.
        page_size: Page size requested by the client.

    Returns:
        PaginatedEnvelope containing reconciliation result items.
    """
    items = [_present_result(e.result) for e in dto.items]

    return PaginatedEnvelope(
        items=items,
        total=len(items),
        page=page,
        page_size=page_size,
    )


def present_reconciliation_summary(
    dto: GetReconciliationSummaryResponseDTO,
) -> SuccessEnvelope[list[ReconciliationSummaryBucketHTTP]]:
    """Present a reconciliation summary response as a success envelope.

    Args:
        dto: Application DTO containing summary buckets.

    Returns:
        SuccessEnvelope containing a list of ReconciliationSummaryBucketHTTP.
    """
    buckets = [
        ReconciliationSummaryBucketHTTP(
            fiscal_year=b.fiscal_year,
            fiscal_period=b.fiscal_period,
            version_sequence=b.version_sequence,
            rule_category=b.rule_category,
            pass_count=b.pass_count,
            warn_count=b.warn_count,
            fail_count=b.fail_count,
        )
        for b in dto.buckets
    ]
    return SuccessEnvelope(data=buckets)


def _present_result(r: Any) -> ReconciliationResultHTTP:
    """Map a single reconciliation result into its HTTP schema.

    Args:
        r: A reconciliation result object produced by the domain/application layer.

    Returns:
        ReconciliationResultHTTP representation of the input result.
    """
    return ReconciliationResultHTTP(
        cik=r.statement_identity.cik,
        statement_type=r.statement_identity.statement_type.value,
        fiscal_year=r.statement_identity.fiscal_year,
        fiscal_period=r.statement_identity.fiscal_period.value,
        version_sequence=r.statement_identity.version_sequence,
        rule_id=r.rule_id,
        rule_category=r.rule_category,
        status=r.status,
        severity=r.severity,
        expected_value=r.expected_value,
        actual_value=r.actual_value,
        delta=r.delta,
        dimension_key=r.dimension_key,
        dimension_labels=dict(r.dimension_labels) if r.dimension_labels else None,
        notes=dict(r.notes) if r.notes else None,
    )
