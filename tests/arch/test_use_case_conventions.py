# tests/arch/test_use_case_conventions.py
from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "arche_api"
USE_CASES_ROOT = SRC_ROOT / "application" / "use_cases"
TESTS_ROOT = PROJECT_ROOT / "tests"

GOOGLE_STYLE_RE = re.compile(r"\b(Args|Returns|Raises):", re.MULTILINE)


def _iter_use_case_modules() -> list[tuple[str, Path]]:
    modules: list[tuple[str, Path]] = []
    for path in USE_CASES_ROOT.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(SRC_ROOT)
        module_name = "arche_api." + ".".join(rel.with_suffix("").parts)
        modules.append((module_name, path))
    return modules


def _expected_test_path_for(module_path: Path) -> Path:
    # src/arche_api/application/use_cases/foo/bar.py
    # -> tests/unit/application/use_cases/test_bar.py
    name = module_path.stem
    return TESTS_ROOT / "unit" / "application" / "use_cases" / f"test_{name}.py"


def test_use_cases_have_execute_and_tests_and_docstrings() -> None:
    violations: list[str] = []

    for module_name, path in _iter_use_case_modules():
        module = importlib.import_module(module_name)

        # Enforce a corresponding unit test file exists.
        expected_test_path = _expected_test_path_for(path)
        if not expected_test_path.exists():
            violations.append(
                f"{module_name}: expected unit test file at {expected_test_path} (per Testing Guide)."
            )

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if name.startswith("_") or obj.__module__ != module.__name__:
                continue

            # Heuristic: treat *UseCase classes as actual use cases.
            if not name.endswith("UseCase"):
                continue

            doc = inspect.getdoc(obj) or ""
            if not GOOGLE_STYLE_RE.search(doc):
                violations.append(
                    f"{module_name}.{name} is missing a Google-style docstring "
                    "(expected Args/Returns/Raises)."
                )

            execute = getattr(obj, "execute", None)
            if execute is None or not callable(execute):
                violations.append(f"{module_name}.{name} must define an execute(...) method.")

    if violations:
        raise AssertionError("Use case convention violations:\n" + "\n".join(sorted(violations)))
