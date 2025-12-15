from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from fastapi import APIRouter  # type: ignore[import]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "arche_api"
ROUTERS_ROOT = SRC_ROOT / "adapters" / "routers"

# Router modules that are allowed to have no /v1 prefix (e.g. top-level aggregator).
PREFIX_EXEMPT_MODULES = {
    "arche_api.adapters.routers.api_router",
    "arche_api.adapters.routers.health_router",
    "arche_api.adapters.routers.metrics_router",
    "arche_api.adapters.routers.mcp_router",
    # Legitimate v2 market-data surfaces
    "arche_api.adapters.routers.quotes_router",
    "arche_api.adapters.routers.historical_quotes_router",
}


def _iter_router_files() -> list[tuple[str, Path]]:
    modules: list[tuple[str, Path]] = []
    for path in ROUTERS_ROOT.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(SRC_ROOT)
        module_name = "arche_api." + ".".join(rel.with_suffix("").parts)
        modules.append((module_name, path))
    return modules


def test_routers_do_not_import_domain_entities() -> None:
    violations: list[str] = []

    for module_name, path in _iter_router_files():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("arche_api.domain.entities")
            ):
                violations.append(
                    f"{module_name} imports domain.entities directly; routers must use HTTP schemas, "
                    "not domain entities, in public signatures."
                )

    if violations:
        raise AssertionError(
            "Router violations (domain entities in HTTP signatures):\n" + "\n".join(violations)
        )


def test_routers_use_v1_prefix() -> None:
    violations: list[str] = []

    for module_name, _ in _iter_router_files():
        if module_name in PREFIX_EXEMPT_MODULES:
            continue

        module = importlib.import_module(module_name)
        router_objects = [
            obj for _, obj in inspect.getmembers(module) if isinstance(obj, APIRouter)
        ]
        if not router_objects:
            continue

        for router in router_objects:
            prefix = router.prefix or ""
            if not prefix.startswith("/v1"):
                violations.append(
                    f"{module_name}: router prefix '{prefix}' does not start with '/v1'. "
                    "All public routes must be versioned."
                )

    if violations:
        raise AssertionError("Router prefix violations:\n" + "\n".join(violations))
