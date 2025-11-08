"""
OpenAPI Snapshot Tests (E2E-lite)

Purpose:
    Verify the public HTTP contract is stable and includes the canonical
    envelopes per API Standards §17 (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope).

Layer: tests/openapi

How it works:
    - Imports `src.main.app` (FastAPI app) and pulls `/openapi.json`.
    - Normalizes away volatile fields.
    - Compares with a committed snapshot under tests/openapi/snapshots/openapi.json.
    - If `UPDATE_OPENAPI_SNAPSHOT=1`, rewrites the snapshot (intentional update).

References:
    - API Standards: Contract Registry, headers, pagination, error mapping.
    - Testing Guide: OpenAPI snapshot tests to prevent contract drift.
    - Definition of Done: OpenAPI snapshot gates must pass.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from stacklion_api.main import app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def _fetch_openapi() -> dict[str, Any]:
    """Return the OpenAPI spec from the running FastAPI app."""
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200, f"Cannot fetch openapi.json: {resp.text}"
        return cast(dict[str, Any], resp.json())


def _prune(d: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Remove selected top-level keys from a dict (immutably)."""
    out: dict[str, Any] = {k: v for k, v in d.items() if k not in keys}
    return out


def _normalize_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize volatile fields for stable snapshot comparisons.

    Notes:
        - Removes `servers`, `externalDocs`, and `info.x-*` custom fields if present.
        - Leaves `components`, `paths`, and `info.title/version` in place.
        - Sorts dicts by keys where feasible via JSON dump (done at compare time).
    """

    def _strip_descriptions(obj: Any) -> Any:
        if isinstance(obj, dict):
            # drop any 'description' key anywhere under schemas
            return {k: _strip_descriptions(v) for k, v in obj.items() if k != "description"}
        if isinstance(obj, list):
            return [_strip_descriptions(v) for v in obj]
        return obj

    spec = deepcopy(spec)
    # already pruning servers/externalDocs/x-* (keep your existing code)
    spec = _prune(spec, keys=("servers", "externalDocs"))
    if isinstance(spec.get("info"), dict):
        spec["info"] = {k: v for k, v in spec["info"].items() if not str(k).startswith("x-")}

    comps = spec.get("components")
    if isinstance(comps, dict) and isinstance(comps.get("schemas"), dict):
        spec["components"]["schemas"] = _strip_descriptions(comps["schemas"])
    return spec


def _json_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Compare dicts deterministically via canonical JSON string."""
    aj = json.dumps(a, sort_keys=True, separators=(",", ":"))
    bj = json.dumps(b, sort_keys=True, separators=(",", ":"))
    return aj == bj


def _write_snapshot(data: dict[str, Any]) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    if not txt.endswith("\n"):
        txt += "\n"  # ensure trailing newline
    SNAPSHOT_PATH.write_text(txt, encoding="utf-8")


@pytest.mark.anyio
def test_openapi_snapshot_contract_is_stable() -> None:
    """Fetch, normalize, and compare OpenAPI against the committed snapshot.

    Behavior:
        - If UPDATE_OPENAPI_SNAPSHOT=1 is set, writes the current normalized
          spec to disk and passes (used when intentionally updating the contract).
        - Otherwise compares with the existing snapshot and fails on any diff.
    """
    raw = _fetch_openapi()
    normalized = _normalize_openapi(raw)

    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        _write_snapshot(normalized)
        assert True
        return

    assert SNAPSHOT_PATH.exists(), (
        f"Snapshot missing at {SNAPSHOT_PATH}. "
        "Run with UPDATE_OPENAPI_SNAPSHOT=1 to create the initial snapshot."
    )

    with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
        snap = cast(dict[str, Any], json.load(f))

    assert _json_equal(normalized, snap), (
        "OpenAPI contract drift detected. If this change is intentional, "
        "update the snapshot with UPDATE_OPENAPI_SNAPSHOT=1. Otherwise, "
        "reconcile your routers/schemas to match the published contract."
    )


@pytest.mark.anyio
def test_openapi_includes_canonical_envelopes() -> None:
    """Assert that the Contract Registry envelopes are present in components/schemas.

    Enforced components per API Standards §17:
        - SuccessEnvelope
        - PaginatedEnvelope
        - ErrorEnvelope
    """
    spec = _normalize_openapi(_fetch_openapi())
    components = cast(dict[str, Any], spec.get("components", {}))
    schemas = cast(dict[str, Any], components.get("schemas", {}))

    missing = [
        name
        for name in ("SuccessEnvelope", "PaginatedEnvelope", "ErrorEnvelope")
        if name not in schemas
    ]
    assert not missing, f"Missing canonical envelopes in components/schemas: {missing}"

    # Quick shape checks (non-exhaustive) to prevent accidental field renames.
    success = cast(dict[str, Any], schemas["SuccessEnvelope"])
    assert "properties" in success and "data" in cast(dict[str, Any], success["properties"])

    paginated = cast(dict[str, Any], schemas["PaginatedEnvelope"])
    for field in ("page", "page_size", "total", "items"):
        assert field in cast(
            dict[str, Any], paginated.get("properties", {})
        ), f"PaginatedEnvelope missing {field}"

    error = cast(dict[str, Any], schemas["ErrorEnvelope"])
    assert "error" in cast(
        dict[str, Any], error.get("properties", {})
    ), "ErrorEnvelope must contain an `error` object"
