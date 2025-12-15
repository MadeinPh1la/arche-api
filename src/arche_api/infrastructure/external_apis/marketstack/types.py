# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Marketstack Types.

Summary:
    Typed response structures for Marketstack endpoints.
"""
from __future__ import annotations

from typing import NotRequired, TypedDict


class MarketstackLatestItem(TypedDict):
    symbol: str
    last: float | str
    date: str
    currency: NotRequired[str]
    volume: NotRequired[int | None]


class MarketstackLatestResponse(TypedDict):
    data: list[MarketstackLatestItem]
