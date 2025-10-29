# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
DI: Market Data.

Summary:
    Dependency graph for Marketstack-backed quotes use-case.
"""
from __future__ import annotations

from typing import Annotated, cast

import httpx
from fastapi import Depends

from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackGateway
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


async def get_httpx_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient."""
    return httpx.AsyncClient()


def _extract_marketstack_settings(settings: Settings) -> MarketstackSettings:
    """Extract nested Marketstack settings from application Settings."""
    # mypy: Settings.marketstack may be typed as Any depending on your Settings model;
    # cast to keep the function signature precise.
    return cast(MarketstackSettings, settings.marketstack)


def get_marketstack_settings(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketstackSettings:
    """Return Marketstack settings from application settings."""
    return _extract_marketstack_settings(settings)


async def get_marketstack_gateway(
    client: Annotated[httpx.AsyncClient, Depends(get_httpx_client)],
    cfg: Annotated[MarketstackSettings, Depends(get_marketstack_settings)],
) -> MarketDataGatewayProtocol:
    """Return a MarketDataGatewayProtocol implemented by Marketstack."""
    return MarketstackGateway(client=client, settings=cfg)


async def get_quotes_uc(
    gateway: Annotated[MarketDataGatewayProtocol, Depends(get_marketstack_gateway)],
) -> GetQuotes:
    """Return the GetQuotes use-case wired to the market data gateway."""
    return GetQuotes(gateway=gateway)
