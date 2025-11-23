from __future__ import annotations

import httpx
import pytest
import respx

from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
    EdgarNotFound,
)
from stacklion_api.infrastructure.external_apis.edgar.client import EdgarClient
from stacklion_api.infrastructure.external_apis.edgar.settings import EdgarSettings
from stacklion_api.infrastructure.logging.logger import set_request_context


@pytest.mark.asyncio
@respx.mock
async def test_fetch_company_submissions_happy_path_and_headers_propagated() -> None:
    settings = EdgarSettings()  # uses default base_url and UA
    async with httpx.AsyncClient() as http:
        client = EdgarClient(settings=settings, http=http)

        set_request_context(request_id="req-123", trace_id="trace-abc")

        expected = {"cik": "0000320193", "filings": {"recent": {}}}
        route = respx.get(f"{settings.base_url}/submissions/CIK0000320193.json").mock(
            return_value=httpx.Response(200, json=expected)
        )

        payload = await client.fetch_company_submissions("320193")

        assert route.called
        request = route.calls.last.request
        assert request.headers["X-Request-ID"] == "req-123"
        assert request.headers["x-trace-id"] == "trace-abc"
        assert payload["cik"] == "0000320193"

        set_request_context(request_id=None, trace_id=None)


@pytest.mark.asyncio
@respx.mock
async def test_edgar_client_status_mapping_and_json_validation() -> None:
    settings = EdgarSettings()
    async with httpx.AsyncClient() as http:
        client = EdgarClient(settings=settings, http=http)

        base = settings.base_url.rstrip("/")

        # 404 -> EdgarNotFound
        respx.get(f"{base}/submissions/CIK0000000001.json").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(EdgarNotFound):
            await client.fetch_company_submissions("1")

        # 500 -> EdgarIngestionError (upstream_unavailable)
        respx.get(f"{base}/submissions/CIK0000000002.json").mock(
            return_value=httpx.Response(500, json={"detail": "server error"})
        )
        with pytest.raises(EdgarIngestionError):
            await client.fetch_company_submissions("2")

        # 400 -> EdgarIngestionError (bad_request)
        respx.get(f"{base}/submissions/CIK0000000003.json").mock(
            return_value=httpx.Response(400, json={"detail": "bad request"})
        )
        with pytest.raises(EdgarIngestionError):
            await client.fetch_company_submissions("3")

        # Non-JSON -> EdgarMappingError
        respx.get(f"{base}/submissions/CIK0000000004.json").mock(
            return_value=httpx.Response(200, content=b"<html>not json</html>")
        )
        with pytest.raises(EdgarMappingError):
            await client.fetch_company_submissions("4")
