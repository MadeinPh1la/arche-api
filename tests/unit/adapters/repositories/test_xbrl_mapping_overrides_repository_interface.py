# tests/unit/adapters/repositories/test_xbrl_mapping_overrides_repository_interface.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Interface-level tests for XBRL mapping overrides repository.

These tests assert that the domain repository interface remains a Protocol-style
contract and is not directly instantiable.
"""

from __future__ import annotations

from typing import Protocol

from arche_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository,
)


def test_interface_is_protocol() -> None:
    """The XBRL mapping overrides repository interface must be a Protocol."""
    assert issubclass(XBRLMappingOverridesRepository, Protocol)


def test_interface_cannot_be_instantiated() -> None:
    """Protocol-based repositories must not be instantiated directly."""
    # Protocol classes raise TypeError when instantiated.
    try:
        XBRLMappingOverridesRepository()  # type: ignore[call-arg]
    except TypeError:
        return

    raise AssertionError("XBRLMappingOverridesRepository should not be instantiable.")
