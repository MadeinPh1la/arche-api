# src/stacklion_api/infrastructure/observability/otel.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""OpenTelemetry bootstrap (soft dependency).

This module wires OTLP exporters for traces and metrics using the canonical
application :class:`Settings`. OpenTelemetry is treated as an optional
dependency:

* If the OTEL packages are not importable, this module degrades to a no-op and
  logs a warning instead of crashing import or test collection.
* If ``settings.otel_enabled`` is false, :func:`init_otel` is a no-op.
* If ``settings.otel_exporter_otlp_endpoint`` is set, OTLP exporters will
  be configured to use that endpoint; otherwise library defaults apply.
"""

from __future__ import annotations

import logging
from typing import Any

from stacklion_api.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "init_otel",
    "is_otel_initialized",
    # Exposed for tests to monkeypatch.
    "metrics",
    "trace",
    "OTLPMetricExporter",
    "OTLPSpanExporter",
    "MeterProvider",
    "PeriodicExportingMetricReader",
    "Resource",
    "TracerProvider",
    "BatchSpanProcessor",
]

_OTEL_AVAILABLE: bool = False
_OTEL_INITIALIZED: bool = False

# ---------------------------------------------------------------------------
# Soft imports with indirection to keep mypy happy and tests patchable.
# We import into underscored names, then re-export them as `Any` so that
# tests can monkeypatch the public symbols without type conflicts.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import wiring is exercised indirectly via init_otel
    from opentelemetry import metrics as _metrics
    from opentelemetry import trace as _trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter as _OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as _OTLPSpanExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
    from opentelemetry.sdk.metrics.export import (
        PeriodicExportingMetricReader as _PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
    )

    _OTEL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - only hit when OTEL is absent
    _metrics = None
    _trace = None
    _OTLPMetricExporter = None
    _OTLPSpanExporter = None
    _MeterProvider = None
    _PeriodicExportingMetricReader = None
    _Resource = None
    _TracerProvider = None
    _BatchSpanProcessor = None

    logger.warning(
        "otel.import_failed",
        extra={
            "extra": {
                "message": (
                    "OpenTelemetry packages are not importable; "
                    "observability.otel will behave as a no-op. "
                    "Install the OTEL extras (or [dev] extras) to enable tracing/metrics."
                )
            }
        },
    )

# Public names used by production code and monkeypatched by tests.
metrics: Any = _metrics
trace: Any = _trace
OTLPMetricExporter: Any = _OTLPMetricExporter
OTLPSpanExporter: Any = _OTLPSpanExporter
MeterProvider: Any = _MeterProvider
PeriodicExportingMetricReader: Any = _PeriodicExportingMetricReader
Resource: Any = _Resource
TracerProvider: Any = _TracerProvider
BatchSpanProcessor: Any = _BatchSpanProcessor


def init_otel(service_name: str, service_version: str) -> None:
    """Initialize OpenTelemetry tracing and metrics exporters.

    This function configures OTLP exporters for traces and metrics based on the
    canonical application :class:`Settings`:

    * If ``settings.otel_enabled`` is false, this function is a no-op.
    * If OpenTelemetry is not importable, this function is a no-op and logs a
      structured warning.
    * If ``settings.otel_exporter_otlp_endpoint`` is set, OTLP exporters will
      be configured to use that endpoint; otherwise library defaults apply.

    Args:
        service_name: Logical service name (for example, ``"stacklion-api"``).
        service_version: Deployed service version string.
    """
    global _OTEL_INITIALIZED

    settings = get_settings()

    if not settings.otel_enabled:
        logger.info(
            "otel.disabled",
            extra={
                "extra": {
                    "service": service_name,
                    "version": service_version,
                }
            },
        )
        return

    if not _OTEL_AVAILABLE:
        logger.warning(
            "otel.unavailable",
            extra={
                "extra": {
                    "service": service_name,
                    "version": service_version,
                    "reason": "opentelemetry package not importable",
                }
            },
        )
        return

    if any(
        obj is None
        for obj in (
            metrics,
            trace,
            OTLPMetricExporter,
            OTLPSpanExporter,
            MeterProvider,
            PeriodicExportingMetricReader,
            Resource,
            TracerProvider,
            BatchSpanProcessor,
        )
    ):
        # Defensive guard: if imports partially failed or were modified in a
        # way that leaves required symbols undefined, avoid crashing here.
        logger.warning(
            "otel.incomplete_imports",
            extra={
                "extra": {
                    "service": service_name,
                    "version": service_version,
                }
            },
        )
        return

    # At this point OTEL is importable and enabled in settings.
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )

    # -----------------------------------------------------------------------
    # Tracing
    # -----------------------------------------------------------------------
    if settings.otel_exporter_otlp_endpoint:
        span_exporter = OTLPSpanExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
    else:
        span_exporter = OTLPSpanExporter()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------
    if settings.otel_exporter_otlp_endpoint:
        metric_exporter = OTLPMetricExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
    else:
        metric_exporter = OTLPMetricExporter()

    reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    _OTEL_INITIALIZED = True

    logger.info(
        "otel.initialized",
        extra={
            "extra": {
                "service": service_name,
                "version": service_version,
                "endpoint": (
                    str(settings.otel_exporter_otlp_endpoint)
                    if settings.otel_exporter_otlp_endpoint
                    else "default"
                ),
            }
        },
    )


def is_otel_initialized() -> bool:
    """Return whether OpenTelemetry has been successfully initialized.

    This is a cheap, side-effect-free check that other components can use to
    decide whether to register additional instrumentation.
    """
    return _OTEL_INITIALIZED
