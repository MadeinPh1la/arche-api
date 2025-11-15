# tests/unit/infrastructure/test_otel.py
from __future__ import annotations

from typing import Any

import pytest

from stacklion_api.infrastructure.observability import otel


class _FakeSettings:
    """Minimal fake settings projection for OTEL tests."""

    def __init__(self, *, enabled: bool, endpoint: str | None) -> None:
        self.otel_enabled = enabled
        self.otel_exporter_otlp_endpoint = endpoint
        # These fields are unused by init_otel but present on real Settings.
        self.environment = None  # pragma: no cover


def _install_exporter_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch OTLP exporters and OTEL provider setters with fakes.

    Returns:
        dict: Shared state mutated by the fakes for assertions.
    """
    state: dict[str, Any] = {
        "span_exporter_endpoints": [],
        "metric_exporter_endpoints": [],
        "tracer_provider": None,
        "meter_provider": None,
    }

    class FakeSpanExporter:
        """Span exporter stub capturing endpoint and supporting shutdown."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # Capture endpoint kwarg if present, else None
            state["span_exporter_endpoints"].append(kwargs.get("endpoint"))

        def export(self, spans: Any) -> None:  # pragma: no cover - not exercised
            return None

        def shutdown(self, *args, **kwargs) -> None:  # pragma: no cover - invoked at atexit
            return None

    class FakeMetricExporter:
        """Metric exporter stub capturing endpoint and exposing OTEL attrs."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            state["metric_exporter_endpoints"].append(kwargs.get("endpoint"))
            # Minimal attributes required by PeriodicExportingMetricReader
            self._preferred_temporality = {}
            self._preferred_aggregation = {}

        def export(self, metrics_data: Any) -> None:  # pragma: no cover
            return None

        def shutdown(self, *args, **kwargs) -> None:  # pragma: no cover
            return None

    def fake_set_tracer_provider(provider: Any) -> None:
        state["tracer_provider"] = provider

    def fake_set_meter_provider(provider: Any) -> None:
        state["meter_provider"] = provider

    # Patch the concrete symbols imported in otel.py
    monkeypatch.setattr(otel, "OTLPSpanExporter", FakeSpanExporter, raising=True)
    monkeypatch.setattr(otel, "OTLPMetricExporter", FakeMetricExporter, raising=True)
    monkeypatch.setattr(otel.trace, "set_tracer_provider", fake_set_tracer_provider, raising=True)
    monkeypatch.setattr(otel.metrics, "set_meter_provider", fake_set_meter_provider, raising=True)

    return state


@pytest.mark.parametrize("enabled", [False, True])
def test_init_otel_respects_enabled_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """init_otel should no-op when disabled and configure exporters when enabled."""
    endpoint = "http://collector:4317"
    settings = _FakeSettings(enabled=enabled, endpoint=endpoint)

    # Patch get_settings used inside otel.init_otel
    monkeypatch.setattr(otel, "get_settings", lambda: settings, raising=True)

    state = _install_exporter_fakes(monkeypatch)

    otel.init_otel(service_name="stacklion-api", service_version="1.2.3")

    if not enabled:
        # No exporters or providers should be set when OTEL is disabled.
        assert state["span_exporter_endpoints"] == []
        assert state["metric_exporter_endpoints"] == []
        assert state["tracer_provider"] is None
        assert state["meter_provider"] is None
    else:
        # Enabled: exporters and providers must be configured.
        assert state["span_exporter_endpoints"] == [endpoint]
        assert state["metric_exporter_endpoints"] == [endpoint]
        assert state["tracer_provider"] is not None
        assert state["meter_provider"] is not None


def test_init_otel_uses_default_exporters_when_no_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """When endpoint is unset, exporters should be constructed without endpoint kwarg."""
    settings = _FakeSettings(enabled=True, endpoint=None)
    monkeypatch.setattr(otel, "get_settings", lambda: settings, raising=True)

    state = _install_exporter_fakes(monkeypatch)

    otel.init_otel(service_name="stacklion-api", service_version="0.0.1")

    # One span exporter and one metric exporter, with endpoint kwarg omitted.
    assert state["span_exporter_endpoints"] == [None]
    assert state["metric_exporter_endpoints"] == [None]
    assert state["tracer_provider"] is not None
    assert state["meter_provider"] is not None
