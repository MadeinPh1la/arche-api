# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Health endpoints for Stacklion.

This router exposes liveness and readiness checks suitable for container
orchestrators and load balancers. It is transport-bound (FastAPI) but does not
depend on infrastructure details. Concrete check functions (DB, Redis, etc.)
should be injected via FastAPI dependencies so the application layer remains
decoupled from transport and infra specifics.

Design
------
- `/health/z`     liveness: cheap "is the process up" signal (no external I/O).
- `/health/ready` readiness: aggregates dependency checks and returns 200 when
  healthy, 503 when degraded/down. Payload always includes typed check results.

To wire real checks, override `get_health_probe` in your app composition:

    app.dependency_overrides[get_health_probe] = PostgresRedisProbe(session_factory, redis_client)

Do not import SQLAlchemy, Redis, or other infra from this file to preserve the
adapters boundary.
"""

from __future__ import annotations

import asyncio
import typing as t
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from stacklion_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)
router = APIRouter()


# -----------------------------------------------------------------------------
# Contracts (types and DTOs)
# -----------------------------------------------------------------------------


class HealthState(str, Enum):
    """Overall health classification."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class CheckResult(BaseModel):
    """Result of a single dependency check.

    Attributes:
        name: Logical name of the dependency (e.g., "db", "redis").
        status: One of {"ok","down"} for the specific check.
        detail: Optional human-readable detail (e.g., error message).
        duration_ms: Milliseconds spent on the probe.
    """

    name: str = Field(..., examples=["db", "redis"])
    status: t.Literal["ok", "down"]
    detail: str | None = None
    duration_ms: float


class ReadinessResponse(BaseModel):
    """Aggregated readiness response following a problem-details-like shape.

    Attributes:
        status: Overall service status classification.
        checks: Individual dependency check results.
    """

    status: HealthState
    checks: list[CheckResult] = Field(default_factory=list)


class LivenessResponse(BaseModel):
    """Liveness response indicating the process is running."""

    status: t.Literal["ok"] = "ok"


# -----------------------------------------------------------------------------
# Probe interface and default implementation
# -----------------------------------------------------------------------------


class HealthProbe(t.Protocol):
    """Protocol for dependency health checks.

    Implementations should perform minimal I/O (lightweight `SELECT 1`, `PING`,
    etc.) and return True/False. Exceptions must be handled inside the method
    and converted to False with an explanatory message when appropriate.
    """

    async def db(self) -> tuple[bool, str | None]: ...
    async def redis(self) -> tuple[bool, str | None]: ...


class NoopProbe:
    """Default probe that performs no external I/O.

    This implementation always returns False for each check so that readiness
    accurately reports a "degraded" service when no checks are wired yet.
    Replace with a real probe via `dependency_overrides`.
    """

    async def db(self) -> tuple[bool, str | None]:
        return False, "no db probe configured"

    async def redis(self) -> tuple[bool, str | None]:
        return False, "no redis probe configured"


async def get_health_probe() -> HealthProbe:
    """Dependency provider for `HealthProbe`.

    Override this function in your app composition/root to provide a concrete
    implementation that talks to Postgres/Redis (or other stores).

    Returns:
        A `HealthProbe` instance.
    """
    return NoopProbe()


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@router.get(
    "/z",
    summary="Liveness",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    operation_id="health_liveness",
)
async def liveness() -> LivenessResponse:
    """Return a fast liveness signal (no external I/O)."""
    return LivenessResponse()


@router.get(
    "/ready",
    summary="Readiness",
    response_model=ReadinessResponse,
    responses={503: {"description": "Service degraded or down", "model": ReadinessResponse}},
    operation_id="health_readiness",
)
async def readiness(
    response: Response,
    probe: Annotated[HealthProbe, Depends(get_health_probe)],
) -> ReadinessResponse:
    """Aggregate dependency checks and return overall readiness.

    The response status code is 200 when all checks are "ok", otherwise 503.
    Individual check errors are captured in their `detail` field.

    Args:
        response: FastAPI response object used to mutate the status code.
        probe: Injected health probe implementing dependency checks.

    Returns:
        A `ReadinessResponse` summarizing dependency health.
    """

    loop = asyncio.get_running_loop()

    async def _time(
        name: str, fn: t.Callable[[], t.Awaitable[tuple[bool, str | None]]]
    ) -> CheckResult:
        start = loop.time()
        ok, detail = await fn()
        duration_ms = (loop.time() - start) * 1000.0
        return CheckResult(
            name=name, status="ok" if ok else "down", detail=detail, duration_ms=duration_ms
        )

    # Run checks concurrently and tolerate exceptions inside probe methods.
    results = await asyncio.gather(
        _time("db", probe.db),
        _time("redis", probe.redis),
        return_exceptions=False,
    )

    # Determine overall state.
    all_ok = all(r.status == "ok" for r in results)
    overall = HealthState.OK if all_ok else HealthState.DEGRADED

    payload = ReadinessResponse(status=overall, checks=list(results))

    # Emit structured log with full details.
    logger.info(
        "readiness_probe",
        extra={
            "extra": {
                "overall": payload.status,
                "checks": [r.model_dump() for r in payload.checks],
            }
        },
    )

    # Warn if any single check is slow (>200ms).
    slow = [r for r in results if r.duration_ms > 200.0]
    if slow:
        logger.warning(
            "readiness_probe_slow",
            extra={"extra": {"slow": [r.model_dump() for r in slow]}},
        )

    # Set HTTP 503 when degraded/down, but keep the typed payload.
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return payload
