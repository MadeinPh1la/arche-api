"""
Presenter Test Kit (Unit fixtures & helpers)

Purpose:
    Utilities to test adapter presenters in isolation (no FastAPI required).
    Provides a Response-like stub and a minimal DTO for envelope validation,
    headers, and ETag determinism checks.

Layer: tests/fixtures

Notes:
    - Pure-Python; no network/DB/HTTP framework dependencies.
    - Use in unit tests for `BasePresenter` and any custom presenters.
"""

from __future__ import annotations

from pydantic import Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema


class StubResponse:
    """Minimal Response-like object exposing a mutable headers mapping.

    This is intentionally tiny so unit tests can run without FastAPI/httpx.

    Attributes:
        headers: Mutable mapping of header names to values.
    """

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


class ExampleDTO(BaseHTTPSchema):
    """Minimal adapter-layer DTO used by presenter tests."""

    company_id: str = Field(..., description="UUID string of the company.")
    ticker: str = Field(..., min_length=1, max_length=12, description="Ticker symbol.")
    revenue: str = Field(..., description="Revenue as a decimal string.")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO currency code.")
    statement_date: str = Field(..., description="YYYY-MM-DD.")

    model_config = BaseHTTPSchema.model_config.copy()
