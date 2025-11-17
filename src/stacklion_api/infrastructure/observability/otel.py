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

# ---------------------------------------------------------------------------
# OpenTelemetry imports (soft)
# ---------------------------------------------------------------------------

_OTEL_AVAILABLE = False

try:  # pragma: no cover - import wiring is exercised indirectly via init_otel
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - only hit when OTEL is absent
    # Keep names defined so type-checkers and callers can still import this
    # module without blowing up. All OTEL operations will be short-circuited
    # in `init_otel` when `_OTEL_AVAILABLE` is false.
    metrics = None
    trace = None
    OTLPMetricExporter = object
    OTLPSpanExporter = object
    MeterProvider = object
    PeriodicExportingMetricReader = object
    Resource = object
    TracerProvider = object
    BatchSpanProcessor = object

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
        service_name: Logical service name (e.g., ``"stacklion-api"``).
        service_version: Deployed service version string.
    """
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
        # We already logged at import time; log again here with context.
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

    # At this point OTEL is available and enabled in settings.
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )

    # -----------------------------------------------------------------------
    # Tracing
    # -----------------------------------------------------------------------
    span_exporter: Any
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
    metric_exporter: Any
    if settings.otel_exporter_otlp_endpoint:
        metric_exporter = OTLPMetricExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
    else:
        metric_exporter = OTLPMetricExporter()

    reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

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
