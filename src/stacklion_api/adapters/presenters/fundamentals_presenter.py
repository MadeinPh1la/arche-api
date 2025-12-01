# src/stacklion_api/adapters/presenters/fundamentals_presenter.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Fundamentals and restatement HTTP presenter.

Purpose:
    Convert domain and application-layer modeling DTOs into HTTP-facing
    schemas wrapped in canonical envelopes, suitable for FastAPI routers.

Layer:
    adapters/presenters

Notes:
    - This module is HTTP-agnostic aside from using HTTP schema classes.
      Routers own the FastAPI wiring; presenters own payload shapes.
    - Envelopes follow API_STANDARDS.md:
        * SuccessEnvelope[T]: { "data": T }
        * PaginatedEnvelope[T]: { "page", "page_size", "total", "items": [T] }
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from math import ceil
from typing import cast

from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.schemas.http.envelopes import (
    PaginatedEnvelope,
    RestatementDeltaSuccessEnvelope,
    SuccessEnvelope,
)
from stacklion_api.adapters.schemas.http.fundamentals import (
    DerivedMetricsTimeSeriesPointHTTP,
    FundamentalsTimeSeriesPointHTTP,
    NormalizedStatementViewHTTP,
)
from stacklion_api.application.schemas.dto.edgar import (
    ComputeRestatementDeltaResultDTO,
    RestatementMetricDeltaDTO,
    RestatementSummaryDTO,
)
from stacklion_api.application.use_cases.statements.compute_restatement_delta import (
    ComputeRestatementDeltaResult,
)
from stacklion_api.application.use_cases.statements.get_normalized_statement import (
    NormalizedStatementResult,
)
from stacklion_api.domain.entities.edgar_derived_timeseries import (
    DerivedMetricsTimeSeriesPoint,
)
from stacklion_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
)


def _decimal_to_str(value: Decimal | None) -> str | None:
    """Convert a Decimal (or None) into a JSON-safe string (or None)."""
    if value is None:
        return None
    return format(value, "f")


def _map_fundamentals_point(point: FundamentalsTimeSeriesPoint) -> FundamentalsTimeSeriesPointHTTP:
    """Convert a domain FundamentalsTimeSeriesPoint into its HTTP schema."""
    metrics_http: dict[str, str] = {
        metric.value: _decimal_to_str(amount) or "0" for metric, amount in point.metrics.items()
    }

    return FundamentalsTimeSeriesPointHTTP(
        cik=point.cik,
        statement_type=point.statement_type,
        accounting_standard=point.accounting_standard,
        statement_date=point.statement_date,
        fiscal_year=point.fiscal_year,
        fiscal_period=point.fiscal_period,
        currency=point.currency,
        metrics=metrics_http,
        normalized_payload_version_sequence=point.normalized_payload_version_sequence,
    )


def _map_derived_point(point: DerivedMetricsTimeSeriesPoint) -> DerivedMetricsTimeSeriesPointHTTP:
    """Convert a domain DerivedMetricsTimeSeriesPoint into its HTTP schema."""
    metrics_http: dict[str, str] = {
        metric.value: _decimal_to_str(amount) or "0" for metric, amount in point.metrics.items()
    }

    return DerivedMetricsTimeSeriesPointHTTP(
        cik=point.cik,
        statement_type=point.statement_type,
        accounting_standard=point.accounting_standard,
        statement_date=point.statement_date,
        fiscal_year=point.fiscal_year,
        fiscal_period=point.fiscal_period,
        currency=point.currency,
        metrics=metrics_http,
        normalized_payload_version_sequence=point.normalized_payload_version_sequence,
    )


def present_fundamentals_time_series(
    *,
    points: Iterable[FundamentalsTimeSeriesPoint],
    page: int,
    page_size: int,
) -> PaginatedEnvelope[FundamentalsTimeSeriesPointHTTP]:
    """Present a fundamentals time series as a paginated envelope.

    Pagination is applied in-memory over the already-deterministic list of
    points produced by the application layer. This presenter is responsible
    only for slicing and mapping; the ordering is determined by the domain
    helper.

    Args:
        points:
            Iterable of domain time-series points, already sorted.
        page:
            1-based page index.
        page_size:
            Page size (number of items per page).

    Returns:
        PaginatedEnvelope containing FundamentalsTimeSeriesPointHTTP items.
    """
    items = list(points)
    total = len(items)

    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1

    start = (page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]

    http_items = [_map_fundamentals_point(point) for point in sliced]

    # total pages currently unused, but may be valuable for future metadata.
    _ = ceil(total / page_size) if page_size else 0

    return PaginatedEnvelope[FundamentalsTimeSeriesPointHTTP](
        page=page,
        page_size=page_size,
        total=total,
        items=http_items,
    )


def present_derived_time_series(
    *,
    points: Iterable[DerivedMetricsTimeSeriesPoint],
    page: int,
    page_size: int,
) -> PaginatedEnvelope[DerivedMetricsTimeSeriesPointHTTP]:
    """Present a derived metrics time series as a paginated envelope.

    Pagination is applied in-memory over the already-deterministic list of
    points produced by the application layer. This presenter is responsible
    only for slicing and mapping; the ordering is determined by the domain
    helper.

    Args:
        points:
            Iterable of domain derived-metrics points, already sorted.
        page:
            1-based page index.
        page_size:
            Page size (number of items per page).

    Returns:
        PaginatedEnvelope containing DerivedMetricsTimeSeriesPointHTTP items.
    """
    items = list(points)
    total = len(items)

    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1

    start = (page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]

    http_items = [_map_derived_point(point) for point in sliced]

    _ = ceil(total / page_size) if page_size else 0

    return PaginatedEnvelope[DerivedMetricsTimeSeriesPointHTTP](
        page=page,
        page_size=page_size,
        total=total,
        items=http_items,
    )


def present_restatement_delta(
    *,
    result: ComputeRestatementDeltaResult,
) -> RestatementDeltaSuccessEnvelope:
    """Present a restatement delta result using the EDGAR presenter.

    This keeps the fundamentals facade in lockstep with the canonical EDGAR
    restatement delta envelope and schema, while adapting from the
    ComputeRestatementDeltaResult type returned by the fundamentals
    use case.

    Args:
        result:
            Use-case result containing the domain-level RestatementDelta.

    Returns:
        RestatementDeltaSuccessEnvelope containing the RestatementDeltaHTTP payload.
    """
    delta = result.delta

    # Adapt domain metric deltas → DTOs expected by the EDGAR presenter.
    metric_dtos: list[RestatementMetricDeltaDTO] = []
    for metric, metric_delta in delta.metrics.items():
        metric_dtos.append(
            RestatementMetricDeltaDTO(
                metric=metric,
                old_value=metric_delta.old,
                new_value=metric_delta.new,
                diff=metric_delta.diff,
            ),
        )

    # Derive a conservative summary from the domain delta.
    summary_dto = RestatementSummaryDTO(
        total_metrics_compared=len(delta.metrics),
        total_metrics_changed=len(delta.metrics),
        has_material_change=bool(delta.metrics),
    )

    dto = ComputeRestatementDeltaResultDTO(
        cik=delta.cik,
        statement_type=delta.statement_type,
        fiscal_year=delta.fiscal_year,
        fiscal_period=delta.fiscal_period,
        from_version_sequence=delta.from_version_sequence,
        to_version_sequence=delta.to_version_sequence,
        summary=summary_dto,
        deltas=metric_dtos,
    )

    presenter = EdgarPresenter()
    present_result = presenter.present_restatement_delta(dto=dto, trace_id=None)

    # EdgarPresenter.present_restatement_delta() guarantees `.body` is a
    # SuccessEnvelope[RestatementDeltaHTTP]; the type alias for that in
    # the HTTP layer is RestatementDeltaSuccessEnvelope.
    envelope = cast(RestatementDeltaSuccessEnvelope, present_result.body)
    return envelope


def present_normalized_statement(
    *,
    result: NormalizedStatementResult,
) -> SuccessEnvelope[NormalizedStatementViewHTTP]:
    """Present a normalized statement result with optional version history.

    Args:
        result:
            Use-case result containing the latest statement version and its
            version history for a given identity tuple.

    Returns:
        SuccessEnvelope containing a NormalizedStatementViewHTTP payload.
    """
    # We rely on existing EdgarStatementVersionHTTP mapping elsewhere in the
    # stack (controllers/presenters). Here we simply wrap those projections
    # once routers/controllers provide them as HTTP DTOs. For the HTTP
    # modeling layer, we treat the domain entities as already adapted by
    # the caller.
    #
    # To keep this presenter focused, the router/controller is expected to
    # adapt domain `EdgarStatementVersion` entities into `EdgarStatementVersionHTTP`
    # instances prior to calling this function, or use a thin mapper around
    # this presenter.

    view = NormalizedStatementViewHTTP(
        latest=result.latest_version,
        version_history=list(result.version_history),
    )

    return SuccessEnvelope[NormalizedStatementViewHTTP](data=view)
