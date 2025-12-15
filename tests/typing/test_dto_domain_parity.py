from importlib import import_module


def test_dto_domain_parity():
    dom = import_module("arche_api.domain.entities")
    dto = import_module("arche_api.application.schemas.dto")

    # Prefer explicit exports; otherwise heuristics (PascalCase / *DTO)
    domain_names = getattr(dom, "__all__", [n for n in dir(dom) if n[:1].isupper()])
    dto_names = set(getattr(dto, "__all__", [n for n in dir(dto) if n.endswith("DTO")]))

    missing = [name for name in domain_names if f"{name}DTO" not in dto_names]
    assert not missing, f"Missing DTOs for: {missing}"
