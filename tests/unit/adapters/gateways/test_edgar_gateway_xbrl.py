# tests/unit/adapters/gateways/test_edgar_gateway_xbrl.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from arche_api.adapters.gateways.edgar_gateway import HttpEdgarIngestionGateway
from arche_api.domain.exceptions.edgar import EdgarIngestionError


class _FakeEdgarClient:
    def __init__(self, payload: bytes | None = None, raises: bool = False) -> None:
        self._payload = payload or b"<xbrli:xbrl/>"
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def fetch_xbrl(self, cik: str, accession_id: str) -> bytes:
        self.calls.append((cik, accession_id))
        if self._raises:
            raise RuntimeError("boom")
        return self._payload


@pytest.mark.asyncio
async def test_fetch_xbrl_for_filing_success() -> None:
    client = _FakeEdgarClient(payload=b"<xbrli:xbrl/>", raises=False)
    gateway = HttpEdgarIngestionGateway(client)

    result = await gateway.fetch_xbrl_for_filing(
        cik="0000123456",
        accession_id="0000123456-24-000001",
    )

    assert result == b"<xbrli:xbrl/>"
    assert client.calls == [("0000123456", "0000123456-24-000001")]


@pytest.mark.asyncio
async def test_fetch_xbrl_for_filing_wraps_errors() -> None:
    client = _FakeEdgarClient(raises=True)
    gateway = HttpEdgarIngestionGateway(client)

    with pytest.raises(EdgarIngestionError):
        await gateway.fetch_xbrl_for_filing(
            cik="0000123456",
            accession_id="0000123456-24-000001",
        )
