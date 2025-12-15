from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import Any

REQUIRED_FIELDS: set[str] = {"created_at", "updated_at"}  # extend with "version_id" if applicable


def _field_names(cls: type[Any]) -> set[str]:
    """Return Pydantic model field names without triggering deprecation warnings.

    Preference:
        1) Pydantic v2: `model_fields` (a dict-like mapping)
        2) Pydantic v1 fallback: class __dict__['__fields__'] if present

    Notes:
        - DO NOT use getattr(cls, "__fields__", ...) — it triggers a deprecation warning in v2.
        - Accessing via cls.__dict__.get("__fields__") avoids the deprecation path entirely.
    """
    # v2 path
    fields_map: Mapping[str, Any] | None = getattr(cls, "model_fields", None)
    if isinstance(fields_map, Mapping) and fields_map:
        return set(fields_map.keys())

    # v1 fallback without touching the deprecated attribute
    legacy = cls.__dict__.get("__fields__")
    if isinstance(legacy, Mapping) and legacy:
        return set(legacy.keys())

    return set()


def _iter_dto_names(dto_mod: Any) -> Iterable[str]:
    """Yield DTO class names to check.

    Uses `__all__` if available; otherwise falls back to names ending with `DTO`.
    """
    names = getattr(dto_mod, "__all__", None)
    if isinstance(names, (list, tuple)):
        yield from (n for n in names if isinstance(n, str))
        return
    yield from (n for n in dir(dto_mod) if n.endswith("DTO"))


def test_dto_includes_audit_fields() -> None:
    dto_mod = import_module("arche_api.application.schemas.dto")
    missing_by_type: dict[str, list[str]] = {}

    for name in _iter_dto_names(dto_mod):
        cls = getattr(dto_mod, name, None)
        if not isinstance(cls, type):
            continue  # skip non-classes (re-exports, functions, etc.)

        fields = _field_names(cls)
        missing = sorted(REQUIRED_FIELDS - fields)
        if missing:
            missing_by_type[name] = missing

    assert not missing_by_type, f"DTOs missing audit fields: {missing_by_type}"
