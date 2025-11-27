# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Base DTO (Application Layer).

Purpose:
    Canonical Pydantic base for all application-layer DTOs. Transport-agnostic.

Layer: application/schemas/dto
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseDTO(BaseModel):
    """Base class for application-layer DTOs.

    Notes:
        - Must not import HTTP-specific bases.
        - Enforces strict fields (`extra='forbid'`), matching DoD and EQS.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )
