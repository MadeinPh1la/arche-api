# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Health endpoints (Adapters Layer).

Purpose:
    Expose liveness and readiness signals suitable for container orchestrators and
    load balancers while keeping this adapters layer decoupled from infrastructure.

Design:
    * Adapters boundary respected: no direct DB/Redis imports. Probes are injected.
    * Deterministic OpenAPI: stable operation_id/summary; typed response models.
    * Non-blocking: probes run concurrently; latencies recorded to Prometheus.
    * Testability: a provider instance (`probe_provider`) is the DI token so overrides
      match by identity reliably; `use_cache=False` honors late overrides.
    * Back-compat: `/health/readiness` is canonical; `/health/ready` is an alias
      (`include_in_schema=False`) for existing tooling.
"""

from __future__ import annotations

import asyncio
import typing as t
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status
from pydantic import Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.infrastructure.logging.logger import get_json_logger
from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)

logger = get_json_logger(__name__)
router = APIRouter()


# -----------------------------------------------------------------------------
# Contracts (types & DTOs)
# -----------------------------------------------------------------------------


class HealthState(str, Enum):
    """Overall service health classification."""

    OK = "ok"
    """All checks passed; the service is fully ready."""

    DEGRADED = "degraded"
    """One or more checks failed; the service is not fully ready."""

    DOWN = "down"
    """Reserved for hard failures; not emitted by this router today."""


class CheckResult(BaseHTTPSchema):
    """Result of a single dependency check.

    Attributes:
        name: Logical name for the dependency (e.g., "db", "redis").
        status: Per-check outcome: "ok" when the probe succeeded, otherwise "down".
        detail: Optional human-readable diagnostic detail (e.g., exception message).
        duration_ms: Time spent on the probe in milliseconds (float).
    """

    name: str = Field(..., examples=["db", "redis"])
    status: t.Literal["ok", "down"]
    detail: str | None = None
    duration_ms: float


class ReadinessResponse(BaseHTTPSchema):
    """Aggregated readiness response.

    Attributes:
        status: Overall service classification derived from all checks.
        checks: Individual dependency results in deterministic order (DB, Redis).
    """

    status: HealthState
    checks: list[CheckResult] = Field(default_factory=list)


class LivenessResponse(BaseHTTPSchema):
    """Liveness response indicating the process is running."""

    status: t.Literal["ok"] = "ok"


# -----------------------------------------------------------------------------
# Probe protocol and default implementation
# -----------------------------------------------------------------------------


class HealthProbe(Protocol):
    """Protocol for minimal, non-destructive dependency checks.

    Implementations should keep I/O inexpensive (e.g., `SELECT 1`, `PING`)
    and return a tuple ``(is_ok, detail)`` where ``detail`` is an optional
    diagnostic string suitable for logs/JSON responses.
    """

    async def db(self) -> tuple[bool, str | None]:
        """Probe the primary database dependency.

        Returns:
            A tuple ``(is_ok, detail)`` where:
                * ``is_ok`` is True if the probe succeeded.
                * ``detail`` is an optional diagnostic message.
        """
        ...

    async def redis(self) -> tuple[bool, str | None]:
        """Probe the Redis/cache dependency.

        Returns:
            A tuple ``(is_ok, detail)`` where:
                * ``is_ok`` is True if the probe succeeded.
                * ``detail`` is an optional diagnostic message.
        """
        ...


class NoopProbe:
    """Probe that performs no external I/O and always reports failure.

    This default ensures that readiness surfaces as "degraded" until real
    probes are supplied via dependency injection.
    """

    async def db(self) -> tuple[bool, str | None]:
        """Return a failing result indicating no DB probe is configured."""
        return False, "no db probe configured"

    async def redis(self) -> tuple[bool, str | None]:
        """Return a failing result indicating no Redis probe is configured."""
        return False, "no redis probe configured"


def get_health_probe() -> HealthProbe:
    """Return the default health probe."""
    return NoopProbe()


class ProbeProvider:
    """Dependency token object for readiness routes.

    The instance of this class is used as the DI key for readiness endpoints.
    Overriding this instance in tests/app composition is robust because FastAPI
    matches overrides by identity, and ``use_cache=False`` honors late overrides.
    """

    def __call__(self) -> HealthProbe:
        """Return the current health probe implementation."""
        return get_health_probe()


# Single, well-known provider instance used by the routes below.
probe_provider = ProbeProvider()


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@router.get(
    "/z",
    summary="Liveness",
    operation_id="health_liveness",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
)
async def liveness() -> LivenessResponse:
    """Return a fast liveness signal (no external I/O)."""
    return LivenessResponse()


async def _readiness_impl(response: Response, probe: HealthProbe) -> ReadinessResponse:
    """Execute dependency checks concurrently and derive overall readiness.

    Behavior:
        * Times each probe and records latencies to Prometheus histograms (seconds).
        * Returns HTTP 200 if all checks are "ok"; otherwise HTTP 503.
        * Emits structured JSON logs for observability.
    """
    loop = asyncio.get_running_loop()

    async def _time(
        name: str,
        fn: Callable[[], Awaitable[tuple[bool, str | None]]],
        observe_seconds: Callable[[float], None],
    ) -> CheckResult:
        start = loop.time()
        ok, detail = await fn()
        duration_ms = (loop.time() - start) * 1000.0
        observe_seconds(duration_ms / 1000.0)  # Prometheus expects seconds
        return CheckResult(
            name=name,
            status="ok" if ok else "down",
            detail=detail,
            duration_ms=duration_ms,
        )

    db_hist = get_readyz_db_latency_seconds()
    redis_hist = get_readyz_redis_latency_seconds()

    results = await asyncio.gather(
        _time("db", probe.db, db_hist.observe),
        _time("redis", probe.redis, redis_hist.observe),
    )

    all_ok = all(r.status == "ok" for r in results)
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    payload = ReadinessResponse(
        status=HealthState.OK if all_ok else HealthState.DEGRADED,
        checks=list(results),
    )

    logger.info(
        "readiness_probe",
        extra={
            "extra": {
                "overall": payload.status,
                "checks": [r.model_dump_http() for r in payload.checks],
            }
        },
    )

    slow = [r for r in results if r.duration_ms > 200.0]
    if slow:
        logger.warning(
            "readiness_probe_slow",
            extra={"extra": {"slow": [r.model_dump_http() for r in slow]}},
        )

    return payload


@router.get(
    "/readiness",
    summary="Readiness",
    operation_id="health_readiness",
    response_model=ReadinessResponse,
    responses={503: {"description": "Service degraded or down", "model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    probe: Annotated[HealthProbe, Depends(probe_provider, use_cache=False)],
) -> ReadinessResponse:
    """Canonical readiness endpoint (published in OpenAPI)."""
    return await _readiness_impl(response, probe)


@router.get("/ready", include_in_schema=False)
async def readiness_alias(
    response: Response,
    probe: Annotated[HealthProbe, Depends(probe_provider, use_cache=False)],
) -> ReadinessResponse:
    """Back-compat alias for environments still calling `/health/ready`."""
    return await _readiness_impl(response, probe)
