# tests/unit/mcp/test_capabilities_system.py
from __future__ import annotations

from dataclasses import dataclass

import pytest

from arche_api.mcp.capabilities import system_health as system_health_cap
from arche_api.mcp.capabilities import system_metadata as system_metadata_cap
from arche_api.mcp.client.arche_http import (
    ArcheHTTPClient,
    ArcheHTTPError,
    ArcheHTTPResponse,
)
from arche_api.mcp.schemas.errors import MCPError
from arche_api.mcp.schemas.system import SystemHealthResult, SystemMetadataResult


@dataclass
class FakeSettings:
    api_base_url: str = "https://api.arche.test"


@pytest.mark.anyio
async def test_system_health_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_health(self: ArcheHTTPClient) -> ArcheHTTPResponse:
        return ArcheHTTPResponse(
            status_code=200,
            headers={"x-request-id": "req-health-1"},
            body={"status": "ok"},
        )

    monkeypatch.setattr(
        system_health_cap.ArcheHTTPClient,
        "get_health",
        _fake_get_health,
        raising=False,
    )

    result, error = await system_health_cap.system_health(  # type: ignore[arg-type]
        settings=FakeSettings(),
    )

    assert error is None
    assert result is not None
    assert isinstance(result, SystemHealthResult)
    assert result.status == "ok"
    assert result.source_status == 200
    assert result.request_id == "req-health-1"


@pytest.mark.anyio
async def test_system_health_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_health_error(self: ArcheHTTPClient) -> ArcheHTTPResponse:
        raise ArcheHTTPError(
            message="health endpoint unavailable",
            status_code=503,
            error_code="INTERNAL_ERROR",
            trace_id="trace-health-503",
            retry_after_s=None,
        )

    monkeypatch.setattr(
        system_health_cap.ArcheHTTPClient,
        "get_health",
        _fake_get_health_error,
        raising=False,
    )

    result, error = await system_health_cap.system_health(  # type: ignore[arg-type]
        settings=FakeSettings(),
    )

    assert result is None
    assert isinstance(error, MCPError)
    assert error.type == "INTERNAL_ERROR"
    assert error.http_status == 503
    assert error.retryable is True
    assert error.trace_id == "trace-health-503"


@pytest.mark.anyio
async def test_system_metadata_static_values() -> None:
    result, error = await system_metadata_cap.system_metadata(  # type: ignore[arg-type]
        settings=FakeSettings(),
    )

    assert error is None
    assert result is not None
    assert isinstance(result, SystemMetadataResult)
    assert result.mcp_version == "1.0.0"
    assert result.api_version == "v2"
    assert result.quotes_contract_version == "v1"
    assert "1d" in result.supported_intervals
    assert "1m" in result.supported_intervals
    assert result.max_page_size >= 50
    assert result.max_tickers_per_request == 50
