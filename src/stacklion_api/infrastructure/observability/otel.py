from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from stacklion_api.config.settings import get_settings


def init_otel(service_name: str, service_version: str) -> None:
    """Initialize OpenTelemetry tracing and metrics exporters.

    This function configures an OTLP exporter for traces and metrics based on
    the canonical application :class:`Settings`:

    * If ``settings.otel_enabled`` is false, this function is a no-op.
    * If ``settings.otel_exporter_otlp_endpoint`` is set, OTLP exporters will
      be configured to use that endpoint; otherwise library defaults apply.

    Args:
        service_name: Logical service name.
        service_version: Deployed service version.
    """
    settings = get_settings()
    if not settings.otel_enabled:
        return

    resource = Resource.create({"service.name": service_name, "service.version": service_version})

    # tracing
    if settings.otel_exporter_otlp_endpoint:
        span_exporter = OTLPSpanExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
    else:
        span_exporter = OTLPSpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # metrics
    if settings.otel_exporter_otlp_endpoint:
        metric_exporter = OTLPMetricExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
    else:
        metric_exporter = OTLPMetricExporter()
    reader = PeriodicExportingMetricReader(metric_exporter)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
