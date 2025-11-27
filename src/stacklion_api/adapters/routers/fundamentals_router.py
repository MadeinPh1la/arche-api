# src/stacklion_api/adapters/routers/fundamentals_router.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Fundamentals and restatement HTTP router (v1).

Purpose:
    Expose Bloomberg-class modeling endpoints on top of normalized EDGAR
    statement payloads:

        * GET /v1/fundamentals/time-series
        * GET /v1/fundamentals/restatement-delta
        * GET /v1/fundamentals/normalized-statements

    All endpoints:
        - Are read-only.
        - Use canonical envelopes (SuccessEnvelope / PaginatedEnvelope).
        - Rely on application-layer use cases for domain behavior.
        - Defer error mapping to the global HTTP error handler.

Layer:
    adapters/routers

Notes:
    - This router uses BaseRouter so that versioning and resource prefixing
      (/v1/fundamentals) are consistent with the rest of the API.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Query

from stacklion_api.adapters.presenters.fundamentals_presenter import (
    present_fundamentals_time_series,
    present_restatement_delta,
)
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope, SuccessEnvelope
from stacklion_api.adapters.schemas.http.fundamentals import (
    FundamentalsTimeSeriesPointHTTP,
    NormalizedStatementViewHTTP,
    RestatementDeltaHTTP,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.compute_restatement_delta import (
    ComputeRestatementDeltaRequest,
    ComputeRestatementDeltaUseCase,
)
from stacklion_api.application.use_cases.statements.get_fundamentals_timeseries import (
    GetFundamentalsTimeSeriesRequest,
    GetFundamentalsTimeSeriesUseCase,
)
from stacklion_api.application.use_cases.statements.get_normalized_statement import (
    GetNormalizedStatementRequest,
    GetNormalizedStatementUseCase,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType

# --------------------------------------------------------------------------- #
# Temporary UoW dependency wiring                                             #
# --------------------------------------------------------------------------- #


def get_uow() -> UnitOfWork:  # pragma: no cover - wiring placeholder
    """Return a UnitOfWork for fundamentals endpoints.

    This placeholder exists so that the router can be imported and the test
    suite can run. The actual implementation should be provided by the
    application bootstrap once the modeling layer is fully integrated.
    """
    raise RuntimeError(
        "get_uow dependency for fundamentals_router is not wired yet. "
        "Wire this to the real UnitOfWork factory in the application bootstrap."
    )


# v1 Fundamentals router: /v1/fundamentals/...
router = BaseRouter(version="v1", resource="fundamentals", tags=["Fundamentals"])


@router.get(
    "/time-series",
    summary="Fundamentals time series",
    description=(
        "Return a panel-friendly fundamentals time series derived from "
        "normalized EDGAR statement payloads. The endpoint supports a CIK "
        "universe, canonical metric selection, annual/quarterly frequency, "
        "and a deterministic time window."
    ),
    # Governance requires a generic PaginatedEnvelope schema name in OpenAPI.
    response_model=PaginatedEnvelope,
)
async def get_fundamentals_time_series(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    ciks: Annotated[
        list[str],
        Query(
            ...,
            description=(
                "Universe of companies expressed as CIKs. Multiple CIKs can be "
                "provided via repeated query parameters (e.g., "
                "`?ciks=0000320193&ciks=0000789019`)."
            ),
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description=(
                "Statement type to use as the source of fundamentals " "(e.g., INCOME_STATEMENT)."
            ),
        ),
    ],
    metrics: Annotated[
        list[CanonicalStatementMetric] | None,
        Query(
            description=(
                "Optional subset of canonical metrics to include. When omitted, "
                "all metrics present in the underlying normalized payloads are "
                "considered for each point."
            ),
        ),
    ] = None,
    frequency: Annotated[
        str,
        Query(
            description="Requested frequency: 'annual' (FY) or 'quarterly' (Q1–Q4).",
        ),
    ] = "annual",
    from_date: Annotated[
        date | None,
        Query(
            alias="from",
            description=(
                "Inclusive lower bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to 1994-01-01."
            ),
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            alias="to",
            description=(
                "Inclusive upper bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to today's date."
            ),
        ),
    ] = None,
    page: Annotated[
        int,
        Query(
            ge=1,
            description="1-based page index for pagination.",
        ),
    ] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Maximum number of items to return per page (1–200).",
        ),
    ] = 50,
) -> PaginatedEnvelope[FundamentalsTimeSeriesPointHTTP]:
    """HTTP handler for /v1/fundamentals/time-series."""
    use_case = GetFundamentalsTimeSeriesUseCase(uow=uow)

    req = GetFundamentalsTimeSeriesRequest(
        ciks=ciks,
        statement_type=statement_type,
        metrics=tuple(metrics) if metrics is not None else None,
        frequency=frequency,
        from_date=from_date,
        to_date=to_date,
    )

    series = await use_case.execute(req)

    return present_fundamentals_time_series(
        points=series,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/restatement-delta",
    summary="Restatement delta for a single statement",
    description=(
        "Compute a version-over-version restatement delta for a single "
        "normalized EDGAR statement, returning per-metric changes between "
        "two version sequences."
    ),
    response_model=SuccessEnvelope[RestatementDeltaHTTP],
)
async def get_restatement_delta(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    cik: Annotated[
        str,
        Query(
            ...,
            description="Central Index Key for the filer.",
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description="Statement type (e.g., INCOME_STATEMENT, BALANCE_SHEET).",
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Fiscal year associated with the statement (>= 1).",
        ),
    ],
    fiscal_period: Annotated[
        FiscalPeriod,
        Query(
            ...,
            description="Fiscal period within the year (e.g., FY, Q1, Q2).",
        ),
    ],
    from_version_sequence: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Sequence number for the 'from' (pre-restatement) version.",
        ),
    ],
    to_version_sequence: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Sequence number for the 'to' (post-restatement) version.",
        ),
    ],
    metrics: Annotated[
        list[CanonicalStatementMetric] | None,
        Query(
            description=(
                "Optional subset of canonical metrics to consider. When omitted, "
                "all metrics present in both versions are inspected and only "
                "those that changed are returned."
            ),
        ),
    ] = None,
) -> SuccessEnvelope[RestatementDeltaHTTP]:
    """HTTP handler for /v1/fundamentals/restatement-delta."""
    use_case = ComputeRestatementDeltaUseCase(uow=uow)

    req = ComputeRestatementDeltaRequest(
        cik=cik,
        statement_type=statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        from_version_sequence=from_version_sequence,
        to_version_sequence=to_version_sequence,
        metrics=tuple(metrics) if metrics is not None else None,
    )

    result = await use_case.execute(req)

    return present_restatement_delta(result=result)


@router.get(
    "/normalized-statements",
    summary="Normalized EDGAR statement with version history",
    description=(
        "Return the latest normalized EDGAR statement version for a given "
        "(CIK, statement_type, fiscal_year, fiscal_period) identity tuple, "
        "optionally including its version history."
    ),
    response_model=SuccessEnvelope[NormalizedStatementViewHTTP],
)
async def get_normalized_statement(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    cik: Annotated[
        str,
        Query(
            ...,
            description="Central Index Key for the filer.",
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description="Statement type (e.g., INCOME_STATEMENT, BALANCE_SHEET).",
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Fiscal year associated with the statement (>= 1).",
        ),
    ],
    fiscal_period: Annotated[
        FiscalPeriod,
        Query(
            ...,
            description="Fiscal period within the year (e.g., FY, Q1, Q2).",
        ),
    ],
    include_version_history: Annotated[
        bool,
        Query(
            description="Whether to include full version history in the response.",
        ),
    ] = True,
) -> SuccessEnvelope[NormalizedStatementViewHTTP]:
    """HTTP handler for /v1/fundamentals/normalized-statements."""
    use_case = GetNormalizedStatementUseCase(uow=uow)

    req = GetNormalizedStatementRequest(
        cik=cik,
        statement_type=statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        include_version_history=include_version_history,
    )

    result = await use_case.execute(req)

    view = NormalizedStatementViewHTTP(
        latest=result.latest_version,
        version_history=list(result.version_history),
    )
    return SuccessEnvelope[NormalizedStatementViewHTTP](data=view)
