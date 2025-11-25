# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Dependency wiring for EDGAR controllers.

Purpose:
    Provide FastAPI dependency hooks for the EDGAR HTTP layer. The default
    implementation intentionally raises NotImplementedError so that:

        * Tests can override the dependency with fake controllers.
        * Production wiring can be added once read-side EDGAR use-cases are
          implemented.

Layer:
    dependencies
"""

from __future__ import annotations

from stacklion_api.adapters.controllers.edgar_controller import EdgarController


def get_edgar_controller() -> EdgarController:
    """Return the EDGAR controller instance.

    Notes:
        This placeholder implementation intentionally raises NotImplementedError.
        Application wiring should provide concrete use-cases and construct an
        EdgarController instance for real traffic.

        In tests, this dependency is typically overridden with a fake controller.

    Raises:
        NotImplementedError: Always, until wired by the application.
    """
    raise NotImplementedError(
        "get_edgar_controller is not wired. Provide an implementation that "
        "constructs EdgarController with read-side EDGAR use-cases, or override "
        "this dependency in tests."
    )
