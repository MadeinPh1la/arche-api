from importlib import import_module

REQUIRED_FIELDS = {"created_at", "updated_at"}  # extend with "version_id" if applicable


def test_dto_includes_audit_fields():
    dto_mod = import_module("stacklion_api.application.schemas.dto")
    names = getattr(dto_mod, "__all__", [n for n in dir(dto_mod) if n.endswith("DTO")])
    missing_by_type = {}
    for name in names:
        cls = getattr(dto_mod, name, None)
        if not isinstance(cls, type):
            continue
        # pydantic v2 models have __fields__ mapping
        fields = set(getattr(cls, "model_fields", {}).keys()) or set(
            getattr(cls, "__fields__", {}).keys()
        )
        missing = sorted(REQUIRED_FIELDS - fields)
        if missing:
            missing_by_type[name] = missing
    assert not missing_by_type, f"DTOs missing audit fields: {missing_by_type}"
