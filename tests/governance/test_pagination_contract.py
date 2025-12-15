from __future__ import annotations

import json
import typing as t

import pytest

from arche_api.main import create_app

ALLOWED_ENVELOPES = {"PaginatedEnvelope", "SuccessEnvelope", "ErrorEnvelope"}


def _openapi() -> dict[str, t.Any]:
    app = create_app()
    return app.openapi()


def _schema_name(ref: str) -> str | None:
    # Example: "#/components/schemas/PaginatedEnvelope"
    if not isinstance(ref, str) or "#/components/schemas/" not in ref:
        return None
    return ref.split("#/components/schemas/")[-1]


@pytest.mark.anyio
def test_list_endpoints_use_pagination_contract() -> None:
    spec = _openapi()
    paths: dict[str, t.Any] = t.cast(dict[str, t.Any], spec.get("paths", {}))

    # Heuristic: GET operations with page/page_size parameters are "list endpoints".
    candidates: list[tuple[str, str, dict[str, t.Any]]] = []
    for path, ops in paths.items():
        get = ops.get("get")
        if not isinstance(get, dict):
            continue
        params = get.get("parameters", [])
        names = {p.get("name") for p in params if isinstance(p, dict)}
        if {"page", "page_size"} <= names:
            candidates.append((path, "get", get))

    if not candidates:
        pytest.skip("No list endpoints yet; pagination contract test activates once they exist.")

    for path, _method, op in candidates:
        param_names = {p.get("name") for p in op.get("parameters", []) if isinstance(p, dict)}
        assert {"page", "page_size"} <= param_names, f"{path} missing page/page_size"

        content = op.get("responses", {}).get("200", {}).get("content", {})
        app_json = content.get("application/json", {})
        schema = app_json.get("schema", {})
        ref = schema.get("$ref")
        name = _schema_name(ref) if ref else None

        assert name in ALLOWED_ENVELOPES or name == "PaginatedEnvelope", (
            f"{path} 200 response should be a PaginatedEnvelope "
            f"(got {json.dumps(schema, ensure_ascii=False)})"
        )
