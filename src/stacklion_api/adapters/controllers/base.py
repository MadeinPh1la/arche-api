# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Base Controller.

Summary:
    Canonical base for adapter controllers. Controllers are thin coordinators
    and must not perform I/O beyond orchestrating use-cases.

Layer:
    adapters/controllers
"""
from __future__ import annotations


class BaseController:
    """Marker base for adapter controllers."""

    __slots__ = ()
