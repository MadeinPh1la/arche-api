# Copyright (c)
# SPDX-License-Identifier: MIT
"""OpenTelemetry tracing bootstrap (lazy, idempotent, self-protecting).

This module bootstraps OpenTelemetry for the *process*:
- Soft-imports the OTEL SDK and common instrumentations (FastAPI/ASGI, HTTPX, SQLAlchemy).
- Respects CI/test environments and explicit disable flags.
- Wires an OTLP HTTP exporter only if an endpoint is provided.
- Is safe to call multiple times (idempotent) and never crashes the app.

Environment variables:
    ENVIRONMENT:                 "dev" | "prod" | "test" | "ci" (affects auto-disable)
    OTEL_SDK_DISABLED:           "1"/"true" to disable the SDK
    OTEL_SERVICE_NAME:           Service name (default "arche_api")
    SERVICE_VERSION:             Service version (default "0.0.0")
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP HTTP endpoint, e.g. "http://otel-collector:4318/v1/traces"
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from arche_api.config.settings import get_settings

__all__ = ["configure_tracing"]

logger = logging.getLogger(__name__)
_OTEL_CONFIGURED: bool = False


def _should_disable() -> bool:
    """Return True if tracing bootstrap should be skipped.

    Returns:
        bool: True if tracing bootstrap should be skipped.
    """
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    disabled = os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes"}
    under_pytest = ("pytest" in sys.modules) or bool(os.getenv("PYTEST_CURRENT_TEST"))
    if env in {"test", "ci"} or disabled or under_pytest:
        logger.info("otel.disabled", extra={"environment": env or "unknown"})
        return True
    return False


def _import_otel() -> (
    tuple[Any, Any, Any, Any, Any, Any, type[Any] | None, type[Any] | None, type[Any] | None] | None
):
    """Soft-import the OpenTelemetry SDK and instrumentations.

    Returns:
        Optional[tuple]: (trace, Resource, TracerProvider, BatchSpanProcessor,
        OpenTelemetryMiddleware, FastAPIInstrumentor, HTTPXClientInstrumentor|None,
        SQLAlchemyInstrumentor|None, OTLPSpanExporter|None) if available; else None.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXType: type[Any] | None = HTTPXClientInstrumentor
        except Exception:
            HTTPXType = None

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SAType: type[Any] | None = SQLAlchemyInstrumentor
        except Exception:
            SAType = None

        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            OTLPType: type[Any] | None = OTLPSpanExporter
        except Exception:
            OTLPType = None

        return (
            trace,
            Resource,
            TracerProvider,
            BatchSpanProcessor,
            OpenTelemetryMiddleware,
            FastAPIInstrumentor,
            HTTPXType,
            SAType,
            OTLPType,
        )
    except Exception:
        logger.info("otel.sdk_not_installed; tracing disabled")
        return None


def _build_provider(trace: Any, Resource: Any, TracerProvider: Any) -> tuple[Any, str, str]:
    """Create or reuse a tracer provider and attach a service resource.

    Args:
        trace: ``opentelemetry.trace`` module.
        Resource: Resource factory.
        TracerProvider: Provider class.

    Returns:
        tuple: (provider, service_name, service_version)
    """
    try:
        settings = get_settings()
        service_name = settings.service_name or "arche_api"
        service_version = settings.service_version or "0.0.0"
        deployment_env = settings.environment.value
    except Exception:
        service_name = os.getenv("OTEL_SERVICE_NAME", "arche_api")
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
        # Someone else already set the provider; reuse it
        provider = trace.get_tracer_provider()
        logger.info("otel.provider_existing; proceeding with existing provider")
    return provider, service_name, service_version


def _wire_exporter(
    provider: Any, BatchSpanProcessor: Any, OTLPSpanExporter: type[Any] | None
) -> str:
    """Wire an OTLP HTTP exporter if an endpoint is configured.

    Args:
        provider: Tracer provider instance.
        BatchSpanProcessor: Span processor class.
        OTLPSpanExporter: OTLP exporter class (or None if not available).

    Returns:
        str: Endpoint string if exporter was considered; empty string otherwise.
    """
    settings = None
    try:
        settings = get_settings()
    except Exception:
        settings = None

    if settings and settings.otel_exporter_otlp_endpoint:
        endpoint = str(settings.otel_exporter_otlp_endpoint)
    else:
        endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()

    if endpoint and BatchSpanProcessor and OTLPSpanExporter:
        try:
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            provider.add_span_processor(processor)
        except Exception:
            logger.exception("otel.exporter_init_failed; continuing without exporter")
    else:
        logger.info("otel.exporter_skipped_no_endpoint")
    return endpoint


def _instrument_frameworks(
    app: Any,
    OpenTelemetryMiddleware: Any,
    FastAPIInstrumentor: Any,
    HTTPXClientInstrumentor: type[Any] | None,
    SQLAlchemyInstrumentor: type[Any] | None,
) -> None:
    """Instrument FastAPI/ASGI, HTTPX, and SQLAlchemy if available.

    Args:
        app: FastAPI app instance.
        OpenTelemetryMiddleware: ASGI middleware class.
        FastAPIInstrumentor: FastAPI instrumentation helper.
        HTTPXClientInstrumentor: Optional HTTPX instrumentation class.
        SQLAlchemyInstrumentor: Optional SQLAlchemy instrumentation class.
    """
    FastAPIInstrumentor.instrument_app(app)
    app.add_middleware(OpenTelemetryMiddleware)
    if HTTPXClientInstrumentor is not None:
        try:
            HTTPXClientInstrumentor().instrument()
        except Exception:
            logger.exception("otel.httpx_instrument_failed")
    if SQLAlchemyInstrumentor is not None:
        try:
            SQLAlchemyInstrumentor().instrument()
        except Exception:
            logger.exception("otel.sqlalchemy_instrument_failed")


def configure_tracing(app: Any) -> None:
    """Configure OpenTelemetry tracing for the given FastAPI app.

    This function is idempotent and safe to call multiple times. If OTEL is not
    installed, disabled via environment, or already configured, it will return
    without raising.

    Args:
        app: FastAPI application instance.
    """
    global _OTEL_CONFIGURED
    if _OTEL_CONFIGURED:
        return
    if _should_disable():
        return

    imported = _import_otel()
    if not imported:
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
    ) = imported

    provider, service_name, service_version = _build_provider(trace, Resource, TracerProvider)
    endpoint = _wire_exporter(provider, BatchSpanProcessor, OTLPSpanExporter)

    logger.info(
        "otel.configured",
        extra={
            "service": service_name,
            "version": service_version,
            "endpoint": endpoint or None,
        },
    )

    _instrument_frameworks(
        app,
        OpenTelemetryMiddleware,
        FastAPIInstrumentor,
        HTTPXClientInstrumentor,
        SQLAlchemyInstrumentor,
    )
    _OTEL_CONFIGURED = True
