from datetime import date

import httpx
import pytest
from fastapi import FastAPI

from stacklion_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


def _derived_metrics_path(app: FastAPI) -> str:
    """Resolve the derived-metrics time-series endpoint path."""
    return app.url_path_for("get_derived_metrics_timeseries")


def _make_point(
    *,
    cik: str,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    version_seq: int,
    gross_margin: str,
) -> EdgarDerivedMetricsPointDTO:
    return EdgarDerivedMetricsPointDTO(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        metrics={DerivedMetric.GROSS_MARGIN: gross_margin},
        normalized_payload_version_sequence=version_seq,
    )


class _FakeEdgarControllerSuccess:
    async def get_derived_metrics_timeseries(
        self,
        *,
        ciks,
        statement_type,
        metrics,
        frequency,
        from_date,
        to_date,
    ):
        # Ignore inputs; return a small deterministic panel.
        dto_late = _make_point(
            cik="0000000002",
            statement_date=date(2024, 12, 31),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            version_seq=2,
            gross_margin="0.350000",
        )
        dto_early = _make_point(
            cik="0000000001",
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            version_seq=1,
            gross_margin="0.400000",
        )
        return [dto_late, dto_early]


class _FakeEdgarControllerMappingError:
    async def get_derived_metrics_timeseries(
        self,
        *,
        ciks,
        statement_type,
        metrics,
        frequency,
        from_date,
        to_date,
    ):
        raise EdgarMappingError("mapping failure", details={"reason": "test"})


@pytest.fixture
async def client(app: FastAPI):
    """Async HTTP client using the shared FastAPI app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_happy_path(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Endpoint should return SuccessEnvelope with derived metrics points."""
    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _FakeEdgarControllerSuccess()
    )

    path = _derived_metrics_path(app)

    resp = await client.get(
        path,
        params={
            "ciks": ["0000000001", "0000000002"],
            "statement_type": "INCOME_STATEMENT",
            "frequency": "annual",
            "metrics": ["GROSS_MARGIN"],
            "from_date": "2020-01-01",
            "to_date": "2024-12-31",
        },
    )

    assert resp.status_code == 200
    body = resp.json()

    assert body["data"]["ciks"] == ["0000000001", "0000000002"]
    points = body["data"]["points"]
    assert len(points) == 2
    assert [p["cik"] for p in points] == ["0000000001", "0000000002"]
    assert points[0]["metrics"] == {"GROSS_MARGIN": "0.400000"}
    assert points[1]["metrics"] == {"GROSS_MARGIN": "0.350000"}


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_invalid_cik_rejected(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Non-digit CIK should be rejected with a 400 ErrorEnvelope."""
    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _FakeEdgarControllerSuccess()
    )

    path = _derived_metrics_path(app)

    resp = await client.get(
        path,
        params={
            "ciks": ["ABC123"],
            "statement_type": "INCOME_STATEMENT",
            "frequency": "annual",
        },
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["http_status"] == 400


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_mapping_error_mapped(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Domain EdgarMappingError should be mapped to a 500 EDGAR_MAPPING_ERROR envelope."""
    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _FakeEdgarControllerMappingError()
    )

    path = _derived_metrics_path(app)

    resp = await client.get(
        path,
        params={
            "ciks": ["0000000001"],
            "statement_type": "INCOME_STATEMENT",
            "frequency": "annual",
        },
    )

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "EDGAR_MAPPING_ERROR"
    assert body["error"]["http_status"] == 500
