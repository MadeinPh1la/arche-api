# tests/arch/test_domain_entities_conventions.py
from __future__ import annotations

import ast
import importlib
import inspect
import re
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "arche_api"
ENTITIES_ROOT = SRC_ROOT / "domain" / "entities"

GOOGLE_STYLE_RE = re.compile(r"\b(Args|Attributes):", re.MULTILINE)

FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "httpx",
    "starlette",
    "asyncpg",
    "redis",
    "structlog",
    "logging",
    "arche_api.adapters",
    "arche_api.infrastructure",
)


def _iter_entity_files() -> Iterable[Path]:
    for path in ENTITIES_ROOT.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        yield path


def _module_name_from_path(path: Path) -> str:
    rel = path.relative_to(SRC_ROOT)
    return "arche_api." + ".".join(rel.with_suffix("").parts)


def test_domain_entities_have_no_forbidden_imports() -> None:
    violations: list[str] = []

    for path in _iter_entity_files():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        module_name = _module_name_from_path(path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append(f"{module_name} imports forbidden module {name}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(FORBIDDEN_IMPORT_PREFIXES)
            ):
                violations.append(f"{module_name} imports forbidden module {node.module}")

    if violations:
        raise AssertionError(
            "Forbidden imports in domain entities:\n" + "\n".join(sorted(violations))
        )


def test_domain_entities_have_google_style_docstrings_and_post_init() -> None:
    violations: list[str] = []

    for path in _iter_entity_files():
        module_name = _module_name_from_path(path)
        module = importlib.import_module(module_name)

        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip private or imported classes.
            if name.startswith("_") or obj.__module__ != module.__name__:
                continue

            doc = inspect.getdoc(obj) or ""
            if not GOOGLE_STYLE_RE.search(doc):
                violations.append(
                    f"{module_name}.{name} is missing a Google-style docstring "
                    "(expected 'Args:' or 'Attributes:' section)."
                )

            # For dataclasses, require __post_init__ as invariant hook.
            if hasattr(obj, "__dataclass_fields__") and "__post_init__" not in obj.__dict__:
                violations.append(
                    f"{module_name}.{name} is a dataclass but does not define __post_init__ "
                    "to enforce invariants."
                )

    if violations:
        raise AssertionError(
            "Domain entity convention violations:\n" + "\n".join(sorted(violations))
        )
