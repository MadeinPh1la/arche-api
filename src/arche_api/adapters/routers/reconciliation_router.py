# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR reconciliation HTTP router (v1).

Purpose:
    Expose reconciliation execution and ledger introspection endpoints:
        - POST /v1/edgar/reconciliation/run
        - GET  /v1/edgar/reconciliation/ledger
        - GET  /v1/edgar/reconciliation/summary

Layer:
    adapters/routers
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import Body, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from arche_api.adapters.dependencies.edgar_uow import get_edgar_uow
from arche_api.adapters.presenters.reconciliation_presenter import (
    present_reconciliation_ledger,
    present_reconciliation_summary,
    present_run_reconciliation,
)
from arche_api.adapters.routers.base_router import BaseRouter
from arche_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from arche_api.adapters.schemas.http.reconciliation_schemas import (
    ReconciliationSummaryBucketHTTP,
    RunReconciliationRequestHTTP,
    RunReconciliationResponseHTTP,
)
from arche_api.application.schemas.dto.reconciliation import (
    GetReconciliationLedgerRequestDTO,
    GetReconciliationSummaryRequestDTO,
    RunReconciliationOptionsDTO,
    RunReconciliationRequestDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.application.use_cases.reconciliation.get_reconciliation_ledger import (
    GetReconciliationLedgerUseCase,
)
from arche_api.application.use_cases.reconciliation.get_reconciliation_summary import (
    GetReconciliationSummaryUseCase,
)
from arche_api.application.use_cases.reconciliation.run_reconciliation_for_statement_identity import (
    RunReconciliationForStatementIdentityUseCase,
)
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError, EdgarNotFound
from arche_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)

router = BaseRouter(version="v1", resource="edgar/reconciliation", tags=["EDGAR Reconciliation"])


def get_uow() -> UnitOfWork:
    """FastAPI dependency: return the EDGAR UnitOfWork."""
    return get_edgar_uow()


# ---------------------------------------------------------------------------
# FastAPI dependency / parameter singletons
# (Ruff B008: avoid Query()/Body() calls in argument defaults)
# ---------------------------------------------------------------------------

_UOW_DEP = Depends(get_uow)

_RUN_BODY: Any = Body(...)

_Q_CIK: Any = Query(..., description="Company CIK.")
_Q_STATEMENT_TYPE: Any = Query(..., description="Statement type.")
_Q_FISCAL_YEAR: Any = Query(..., ge=1, description="Fiscal year.")
_Q_FISCAL_PERIOD: Any = Query(..., description="Fiscal period.")
_Q_VERSION_SEQUENCE: Any = Query(..., ge=1, description="Statement version sequence.")
_Q_RECONCILIATION_RUN_ID: Any = Query(default=None, description="Optional run UUID filter.")
_Q_RULE_CATEGORY: Any = Query(default=None, description="Optional category filter.")
_Q_STATUSES: Any = Query(default=None, description="Optional status filter.")
_Q_LIMIT_LEDGER: Any = Query(default=None, ge=1, le=20000, description="Optional row limit.")
_Q_PAGE: Any = Query(default=1, ge=1, description="1-based page index.")
_Q_PAGE_SIZE: Any = Query(default=200, ge=1, le=200, description="Page size (1–200).")

_Q_FISCAL_YEAR_FROM: Any = Query(..., ge=1, description="Inclusive start fiscal year.")
_Q_FISCAL_YEAR_TO: Any = Query(..., ge=1, description="Inclusive end fiscal year.")
_Q_LIMIT_SUMMARY: Any = Query(default=5000, ge=1, le=50000, description="Maximum ledger rows.")


def _trace_id(response: Response) -> str | None:
    """Return the request correlation id (X-Request-ID), if present."""
    return response.headers.get("X-Request-ID")


def _error_envelope(
    *,
    http_status: int,
    code: str,
    message: str,
    trace_id: str | None,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    """Build a standard error envelope."""
    return ErrorEnvelope(
        error=ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details=details or {},
            trace_id=trace_id,
        ),
    )


@router.post(
    "/run",
    summary="Run reconciliation for a statement identity",
    description=(
        "Run accounting identity, rollforward, calendar, FX, and segment checks "
        "for a statement identity tuple. Results are appended to the persistent "
        "reconciliation ledger and returned deterministically."
    ),
    response_model=cast(Any, SuccessEnvelope[RunReconciliationResponseHTTP]),
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def run_reconciliation(
    request: Request,
    response: Response,
    body: RunReconciliationRequestHTTP = _RUN_BODY,
    uow: UnitOfWork = _UOW_DEP,
) -> SuccessEnvelope[RunReconciliationResponseHTTP] | JSONResponse:
    """Run reconciliation for a statement identity tuple."""
    del request
    trace_id = _trace_id(response)

    use_case = RunReconciliationForStatementIdentityUseCase(uow=uow)

    try:
        dto = await use_case.execute(
            RunReconciliationRequestDTO(
                cik=body.cik,
                statement_type=body.statement_type,
                fiscal_year=body.fiscal_year,
                fiscal_period=body.fiscal_period,
                options=RunReconciliationOptionsDTO(
                    rule_categories=tuple(body.rule_categories) if body.rule_categories else None,
                    deep=body.deep,
                    fiscal_year_window=body.fiscal_year_window,
                ),
            )
        )
        return present_run_reconciliation(dto)

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except EdgarNotFound as exc:
        error = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENT_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception("reconciliation.api.run.unhandled", extra={"trace_id": trace_id})
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Reconciliation run failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


@router.get(
    "/ledger",
    summary="Get reconciliation ledger for a statement identity",
    description="Return reconciliation checks for a statement identity in deterministic order.",
    # Governance requires the base schema name "PaginatedEnvelope" (non-parameterized).
    response_model=PaginatedEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_reconciliation_ledger(
    request: Request,
    response: Response,
    uow: UnitOfWork = _UOW_DEP,
    cik: str = _Q_CIK,
    statement_type: StatementType = _Q_STATEMENT_TYPE,
    fiscal_year: int = _Q_FISCAL_YEAR,
    fiscal_period: FiscalPeriod = _Q_FISCAL_PERIOD,
    version_sequence: int = _Q_VERSION_SEQUENCE,
    reconciliation_run_id: str | None = _Q_RECONCILIATION_RUN_ID,
    rule_category: ReconciliationRuleCategory | None = _Q_RULE_CATEGORY,
    statuses: list[ReconciliationStatus] | None = _Q_STATUSES,
    limit: int | None = _Q_LIMIT_LEDGER,
    page: int = _Q_PAGE,
    page_size: int = _Q_PAGE_SIZE,
) -> PaginatedEnvelope[Any] | JSONResponse:
    """Return reconciliation ledger entries for a statement identity."""
    del request
    trace_id = _trace_id(response)

    use_case = GetReconciliationLedgerUseCase(uow=uow)

    try:
        dto = await use_case.execute(
            GetReconciliationLedgerRequestDTO.from_primitives(  # type: ignore[attr-defined]
                cik=cik.strip(),
                statement_type=statement_type,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                version_sequence=version_sequence,
                reconciliation_run_id=reconciliation_run_id,
                rule_category=rule_category,
                statuses=tuple(statuses) if statuses else None,
                limit=limit,
            )
        )
        return present_reconciliation_ledger(dto, page=page, page_size=page_size)

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception("reconciliation.api.ledger.unhandled", extra={"trace_id": trace_id})
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Reconciliation ledger endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


@router.get(
    "/summary",
    summary="Get reconciliation summary for a fiscal-year window",
    description="Return PASS/WARN/FAIL counts by category over a multi-year window.",
    response_model=cast(Any, SuccessEnvelope[list[ReconciliationSummaryBucketHTTP]]),
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_reconciliation_summary(
    request: Request,
    response: Response,
    uow: UnitOfWork = _UOW_DEP,
    cik: str = _Q_CIK,
    statement_type: StatementType = _Q_STATEMENT_TYPE,
    fiscal_year_from: int = _Q_FISCAL_YEAR_FROM,
    fiscal_year_to: int = _Q_FISCAL_YEAR_TO,
    rule_category: ReconciliationRuleCategory | None = _Q_RULE_CATEGORY,
    limit: int = _Q_LIMIT_SUMMARY,
) -> SuccessEnvelope[list[ReconciliationSummaryBucketHTTP]] | JSONResponse:
    """Return reconciliation summary buckets for a company/year window."""
    del request
    trace_id = _trace_id(response)

    if fiscal_year_from > fiscal_year_to:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="fiscal_year_from must be <= fiscal_year_to.",
            trace_id=trace_id,
            details={"fiscal_year_from": fiscal_year_from, "fiscal_year_to": fiscal_year_to},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    use_case = GetReconciliationSummaryUseCase(uow=uow)

    try:
        dto = await use_case.execute(
            GetReconciliationSummaryRequestDTO(
                cik=cik.strip(),
                statement_type=statement_type.value,
                fiscal_year_from=fiscal_year_from,
                fiscal_year_to=fiscal_year_to,
                rule_category=rule_category,
                limit=limit,
            )
        )
        return present_reconciliation_summary(dto)

    except Exception as exc:  # pragma: no cover
        logger.exception("reconciliation.api.summary.unhandled", extra={"trace_id": trace_id})
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Reconciliation summary endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))
