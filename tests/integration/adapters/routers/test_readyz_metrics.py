from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from prometheus_client.parser import text_string_to_metric_families

from stacklion_api.main import app


def _readiness_path_from_openapi() -> str:
    spec: dict[str, Any] = app.openapi()
    for path, methods in spec.get("paths", {}).items():
        for method_data in (methods or {}).values():
            if (
                isinstance(method_data, dict)
                and method_data.get("operationId") == "health_readiness"
            ):
                return path
    return "/v1/health/readiness"


@pytest.mark.anyio
async def test_readyz_exposes_latency_metrics(http_client: AsyncClient) -> None:
    """Trigger readiness (healthy or degraded) and assert histograms increment."""
    readiness_path = _readiness_path_from_openapi()

    r1 = await http_client.get(readiness_path)
    # CI DB user may be missing; degraded 503 is acceptable for this test
    assert r1.status_code in (200, 503), r1.text

    r2 = await http_client.get("/metrics")
    assert r2.status_code == 200
    body = r2.text

    families = {mf.name: mf for mf in text_string_to_metric_families(body)}
    assert "readyz_db_latency_seconds" in families, body
    assert "readyz_redis_latency_seconds" in families, body

    def count_of(family_name: str) -> float:
        mf = families[family_name]
        # `mf.samples` items are `Sample` namedtuples; use attributes for robustness
        for s in mf.samples:
            # `s.name` like 'readyz_db_latency_seconds_count'
            if s.name.endswith("_count"):
                # s.value is already numeric; timestamp/exemplar fields are ignored
                try:
                    return float(s.value)
                except Exception:
                    return 0.0
        return 0.0

    assert count_of("readyz_db_latency_seconds") >= 1.0, body
    assert count_of("readyz_redis_latency_seconds") >= 1.0, body
