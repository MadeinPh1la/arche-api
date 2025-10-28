# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Tracing bootstrap (lazy & self-protecting).

- No hard dependency on OTEL packages (soft imports with graceful fallback).
- Early no-op in tests/CI or when OTEL_SDK_DISABLED is true.
- Exporter only configured if OTEL_EXPORTER_OTLP_ENDPOINT is set.
- Idempotent: safe to call multiple times.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)
_OTEL_CONFIGURED: bool = False


def _should_disable() -> bool:
    """Return True if tracing should be disabled for this process."""
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    disabled = os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes"}
    under_pytest = ("pytest" in sys.modules) or bool(os.getenv("PYTEST_CURRENT_TEST"))
    if env in {"test", "ci"} or disabled or under_pytest:
        logger.info("otel.disabled", extra={"environment": env or "unknown"})
        return True
    return False


def _import_otel() -> (
    tuple[Any, Any, Any, Any, Any, Any, Any | None, Any | None, Any | None] | None
):
    """Soft-import OTEL SDK & instrumentations; return None if unavailable."""
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        except Exception:  # pragma: no cover
            HTTPXClientInstrumentor = None
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        except Exception:  # pragma: no cover
            SQLAlchemyInstrumentor = None
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except Exception:  # pragma: no cover
            OTLPSpanExporter = None
        return (
            trace,
            Resource,
            TracerProvider,
            BatchSpanProcessor,
            OpenTelemetryMiddleware,
            FastAPIInstrumentor,
            HTTPXClientInstrumentor,
            SQLAlchemyInstrumentor,
            OTLPSpanExporter,
        )
    except Exception:
        logger.info("otel.sdk_not_installed; tracing disabled")
        return None


def _build_provider(trace: Any, Resource: Any, TracerProvider: Any) -> tuple[Any, str, str]:
    """Create a provider with a service resource, falling back if one exists."""
    service_name = os.getenv("OTEL_SERVICE_NAME", "stacklion-api")
    service_version = os.getenv("SERVICE_VERSION", "0.0.0")
    deployment_env = os.getenv("ENVIRONMENT", "dev")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": deployment_env,
        }
    )
    try:
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
    except Exception:
        provider = trace.get_tracer_provider()
        logger.info("otel.provider_existing; proceeding with existing provider")
    return provider, service_name, service_version


def _wire_exporter(provider: Any, BatchSpanProcessor: Any, OTLPSpanExporter: Any | None) -> str:
    """Wire OTLP HTTP exporter if endpoint is set; return endpoint or ''."""
    endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if endpoint and BatchSpanProcessor and OTLPSpanExporter:
        try:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except Exception:
            logger.exception("otel.exporter_init_failed; continuing without exporter")
    else:
        logger.info("otel.exporter_skipped_no_endpoint")
    return endpoint


def _instrument_frameworks(
    app: Any,
    OpenTelemetryMiddleware: Any,
    FastAPIInstrumentor: Any,
    HTTPXClientInstrumentor: Any | None,
    SQLAlchemyInstrumentor: Any | None,
) -> None:
    """Instrument FastAPI/ASGI, HTTPX, and SQLAlchemy (global) if available."""
    # FastAPI / ASGI
    try:
        FastAPIInstrumentor.instrument_app(app)
        app.add_middleware(OpenTelemetryMiddleware)
    except Exception:
        logger.info("otel.fastapi_or_asgi_instrumentation_missing; skipping")

    # HTTPX
    try:
        if HTTPXClientInstrumentor:
            HTTPXClientInstrumentor().instrument()
    except Exception:
        logger.info("otel.httpx_instrumentation_missing; skipping")

    # SQLAlchemy (global instrumentation)
    try:
        if SQLAlchemyInstrumentor:
            SQLAlchemyInstrumentor().instrument(
                enable_commenter=True, commenter_options={"with_params": True}
            )
    except Exception:
        logger.info("otel.sqlalchemy_instrumentation_missing_or_failed; skipping")


def configure_tracing(app: Any) -> None:
    """Initialize OpenTelemetry tracing and auto-instrumentation (best-effort)."""
    global _OTEL_CONFIGURED
    if _OTEL_CONFIGURED or _should_disable():
        return

    otel = _import_otel()
    if not otel:
        return
    (
        trace,
        Resource,
        TracerProvider,
        BatchSpanProcessor,
        OpenTelemetryMiddleware,
        FastAPIInstrumentor,
        HTTPXClientInstrumentor,
        SQLAlchemyInstrumentor,
        OTLPSpanExporter,
    ) = otel

    provider, service_name, service_version = _build_provider(trace, Resource, TracerProvider)
    endpoint = _wire_exporter(provider, BatchSpanProcessor, OTLPSpanExporter)
    _instrument_frameworks(
        app,
        OpenTelemetryMiddleware,
        FastAPIInstrumentor,
        HTTPXClientInstrumentor,
        SQLAlchemyInstrumentor,
    )

    _OTEL_CONFIGURED = True
    logger.info(
        "otel.tracing_configured",
        extra={"service": service_name, "version": service_version, "endpoint": endpoint or "none"},
    )
