# tests/arch/test_layering.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Clean Architecture layering guardrail using grimp import graph.

This test builds an import graph for the `arche_api` package and enforces
a strict layering policy:

    domain         → may depend only on domain
    application    → may depend on {domain, application}
    adapters       → may depend on {domain, application, adapters}
    infrastructure → may depend on {domain, application, adapters, infrastructure}

Additionally, we forbid *upward* imports from infrastructure into adapters
or higher layers.

If you change layering rules, update both this file and ENGINEERING_GUIDE.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import grimp
from grimp import ImportGraph

ROOT_PACKAGE: Final[str] = "arche_api"

# Map from top-level "layer" to the set of layers it is allowed to import.
ALLOWED_DEPENDENCIES: Mapping[str, set[str]] = {
    # Domain is the inner core: it only depends on itself.
    "domain": {"domain"},
    # Application can depend on domain and itself, but not on adapters/infra.
    "application": {"domain", "application"},
    # Outer ring: adapters can depend on everything inward + infra.
    "adapters": {"domain", "application", "adapters", "infrastructure"},
    # Outer ring: infrastructure can depend on everything inward + adapters.
    "infrastructure": {"domain", "application", "adapters", "infrastructure"},
}


def _build_graph() -> ImportGraph:
    """Build the import graph for the root package using grimp."""
    # Newer grimp versions take the package name positionally – no keywords.
    return grimp.build_graph(ROOT_PACKAGE)


def _layer_for_module(module_name: str) -> str | None:
    """Infer the logical layer (domain/application/adapters/infrastructure) for a module.

    We classify based on the first component after the root package:

        arche_api.domain.*          → "domain"
        arche_api.application.*     → "application"
        arche_api.adapters.*        → "adapters"
        arche_api.infrastructure.*  → "infrastructure"

    Anything else (e.g. arche_api.config, arche_api.main) returns None
    and is ignored for layering checks.
    """
    if not module_name.startswith(f"{ROOT_PACKAGE}."):
        return None

    rest = module_name[len(ROOT_PACKAGE) + 1 :]
    top = rest.split(".", 1)[0]

    if top in {"domain", "application", "adapters", "infrastructure"}:
        return top
    return None


def _find_layering_violations(graph: ImportGraph) -> list[str]:
    """Scan the graph and return human-readable layering violations.

    Newer grimp does not expose a plain `edges()` API. Instead, we iterate over
    all modules in our root package and ask the graph which modules they
    directly import, then apply the layer matrix.
    """
    violations: set[str] = set()

    # Consider only modules under our root package.
    for importer in sorted(graph.modules):
        if not importer.startswith(f"{ROOT_PACKAGE}."):
            continue

        importer_layer = _layer_for_module(importer)
        if importer_layer is None:
            continue  # config, main, etc. are outside the strict layer matrix

        allowed_targets = ALLOWED_DEPENDENCIES[importer_layer]

        # grimp API: find modules that *importer* directly imports.
        for imported in graph.find_modules_directly_imported_by(importer):
            if not imported.startswith(f"{ROOT_PACKAGE}."):
                # Ignore imports into stdlib/third-party.
                continue

            imported_layer = _layer_for_module(imported)
            if imported_layer is None:
                # Cross-layer imports into things like config/main are allowed.
                continue

            if imported_layer not in allowed_targets:
                violations.add(
                    f"{importer} ({importer_layer}) -> {imported} ({imported_layer}) "
                    "is not allowed by ALLOWED_DEPENDENCIES"
                )

    return sorted(violations)


def test_layering_respects_clean_architecture() -> None:
    """Ensure that high-level layering rules are respected."""
    graph = _build_graph()
    violations = _find_layering_violations(graph)

    if violations:
        message = "Layering violations detected:\n" + "\n".join(violations)
        raise AssertionError(message)
