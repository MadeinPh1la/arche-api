# tests/openapi/test_openapi_snapshot.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""OpenAPI Snapshot Tests (E2E-lite)

Purpose:
    Verify the public HTTP contract is stable and includes the canonical
    envelopes per API Standards §17 (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope).

Layer:
    tests/openapi

How it works:
    - Builds a FastAPI app and fetches `/openapi.json`.
    - Normalizes away volatile/non-contract fields.
    - Compares with a committed snapshot under tests/openapi/snapshots/openapi.json.
    - If `UPDATE_OPENAPI_SNAPSHOT=1`, rewrites the snapshot (intentional change).

Notes:
    - Keep this test strict on shapes (components + paths + params), lenient on
      wording and framework-generated metadata that tends to churn.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"
DEBUG_DIR = Path(__file__).parent / "debug"
DEBUG_ACTUAL = DEBUG_DIR / "openapi_actual_normalized.json"
DEBUG_EXPECTED = DEBUG_DIR / "openapi_snapshot_normalized.json"


# --------------------------------------------------------------------------- #
# Deterministic environment for OpenAPI tests
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _stable_openapi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a deterministic environment for OpenAPI generation.

    This ensures that the app built inside these tests sees the same config
    locally and in CI, so the normalized OpenAPI spec is stable and matches
    the committed snapshot.
    """
    # Environment identity
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SERVICE_NAME", "arche_api")
    monkeypatch.setenv("SERVICE_VERSION", "0.0.0")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    # HTTP / CORS
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    # Database / cache
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://arche:arche@127.0.0.1:5432/arche_test",
    )
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/2")

    # Celery (if used)
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/3")

    # External providers
    monkeypatch.setenv("MARKETSTACK_API_KEY", "__test__")
    monkeypatch.setenv("EDGAR_BASE_URL", "https://data.sec.gov")

    # Rate limiting
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("RATE_LIMIT_BURST", "5")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "1")

    # Auth (HS256 test mode)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_ALGORITHM", "HS256")
    monkeypatch.setenv("AUTH_HS256_SECRET", "test-secret")

    # OpenTelemetry
    monkeypatch.setenv("OTEL_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")

    # Clerk (dummy test configuration)
    monkeypatch.setenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_arche_test")
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_arche_test")
    monkeypatch.setenv(
        "CLERK_ISSUER",
        "https://arche-test.clerk.accounts.dev",
    )
    monkeypatch.setenv("CLERK_AUDIENCE", "arche_api")
    monkeypatch.setenv(
        "CLERK_JWKS_URL",
        "https://arche-test.clerk.accounts.dev/.well-known/jwks.json",
    )
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", "whsec_test")

    # Kill any internal "test mode" shortcuts that might alter routers.
    monkeypatch.delenv("STACKLION_TEST_MODE", raising=False)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fetch_openapi() -> dict[str, Any]:
    """Return the OpenAPI spec from a freshly built FastAPI app.

    We *reload* settings and main after the environment fixture has run to
    avoid cross-test contamination and to ensure the OpenAPI spec is generated
    under the deterministic test configuration.
    """
    # Import here so that the autouse fixture can set env vars first.
    import arche_api.config.settings as settings_module
    import arche_api.main as main_module

    # Ensure settings & main pick up the current environment (from fixture).
    importlib.reload(settings_module)
    importlib.reload(main_module)

    app = main_module.create_app()
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200, f"Cannot fetch openapi.json: {resp.text}"
        return cast(dict[str, Any], resp.json())


def _prune(d: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Remove selected top-level keys from a dict (immutably)."""
    return {k: v for k, v in d.items() if k not in keys}


def _strip_descriptions(obj: Any) -> Any:
    """Drop 'description' keys recursively (used for schemas)."""
    if isinstance(obj, dict):
        return {k: _strip_descriptions(v) for k, v in obj.items() if k != "description"}
    if isinstance(obj, list):
        return [_strip_descriptions(v) for v in obj]
    return obj


def _strip_path_noise(obj: Any) -> Any:
    """Drop non-contract, high-churn fields under `paths`."""
    if isinstance(obj, dict):
        noisy = {"summary", "description", "operationId", "examples"}
        return {k: _strip_path_noise(v) for k, v in obj.items() if k not in noisy}
    if isinstance(obj, list):
        return [_strip_path_noise(v) for v in obj]
    return obj


def _normalize_enums_and_required(obj: Any) -> Any:
    """Recursively sort enum and required lists for determinism."""
    if isinstance(obj, dict):
        normalized: dict[str, Any] = {}
        for key, value in obj.items():
            if key in {"enum", "required"} and isinstance(value, list):
                normalized[key] = sorted(value)
            else:
                normalized[key] = _normalize_enums_and_required(value)
        return normalized

    if isinstance(obj, list):
        return [_normalize_enums_and_required(v) for v in obj]

    return obj


def _normalize_misc_lists(obj: Any) -> Any:
    """Normalize other order-insensitive lists (tags, parameters, security, etc.).

    Contract semantics do not depend on order for:
        - tags (list[str])
        - parameters (list[dict]) → sorted by (name, in, full-json)
        - security (list[dict]) → sorted by key name
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "tags" and isinstance(value, list) and all(isinstance(x, str) for x in value):
                out[key] = sorted(value)
            elif (
                key == "parameters"
                and isinstance(value, list)
                and all(isinstance(x, dict) for x in value)
            ):
                normalized_params = [_normalize_misc_lists(p) for p in value]
                out[key] = sorted(
                    normalized_params,
                    key=lambda p: (
                        str(p.get("name", "")),
                        str(p.get("in", "")),
                        json.dumps(p, sort_keys=True, separators=(",", ":")),
                    ),
                )
            elif (
                key == "security"
                and isinstance(value, list)
                and all(isinstance(x, dict) for x in value)
            ):
                # Sort security requirements by key name for stability.
                normalized_sec = []
                for sec_obj in value:
                    if isinstance(sec_obj, dict):
                        normalized_sec.append(
                            {
                                k: v
                                for k, v in sorted(sec_obj.items(), key=lambda item: str(item[0]))
                            }
                        )
                    else:
                        normalized_sec.append(sec_obj)
                out[key] = sorted(
                    normalized_sec,
                    key=lambda s: json.dumps(s, sort_keys=True, separators=(",", ":")),
                )
            else:
                out[key] = _normalize_misc_lists(value)
        return out

    if isinstance(obj, list):
        return [_normalize_misc_lists(x) for x in obj]

    return obj


def _normalize_openapi(spec: dict[str, Any]) -> dict[str, Any]:
    """Normalize volatile fields for stable snapshot comparisons.

    Rules:
        - Remove top-level 'servers' and 'externalDocs'.
        - Remove 'info.x-*' vendor fields (retain title/version).
        - Strip 'description' from component schemas to avoid wording churn.
        - Strip 'summary', 'description', 'operationId', 'examples' under paths.
        - Sort `enum` and `required` lists for deterministic ordering.
        - Normalize other order-insensitive lists:
            * tags
            * parameters
            * security
        - Leave component schema SHAPES, parameter names/types, and response
          content schemas intact (these define the public contract).
    """
    spec = deepcopy(spec)

    # Drop top-level noise
    spec = _prune(spec, keys=("servers", "externalDocs"))

    # Remove vendor-specific info fields
    if isinstance(spec.get("info"), dict):
        spec["info"] = {k: v for k, v in spec["info"].items() if not str(k).startswith("x-")}

    # Prune descriptions from component schemas (shape remains intact)
    comps = spec.get("components")
    if isinstance(comps, dict) and isinstance(comps.get("schemas"), dict):
        spec["components"]["schemas"] = _strip_descriptions(comps["schemas"])

    # Prune churny path-level fields (summary/description/operationId/examples)
    if "paths" in spec and isinstance(spec["paths"], dict):
        spec["paths"] = _strip_path_noise(spec["paths"])

    # Normalize enum / required ordering everywhere
    spec = _normalize_enums_and_required(spec)

    # Normalize other order-insensitive lists
    spec = _normalize_misc_lists(spec)

    return spec


def _json_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Compare dicts deterministically via canonical JSON string.

    On mismatch, write both normalized documents to debug files so we can diff.
    """
    aj = json.dumps(a, sort_keys=True, separators=(",", ":"))
    bj = json.dumps(b, sort_keys=True, separators=(",", ":"))
    if aj == bj:
        # Best-effort cleanup of stale debug files
        if DEBUG_ACTUAL.exists():
            DEBUG_ACTUAL.unlink()
        if DEBUG_EXPECTED.exists():
            DEBUG_EXPECTED.unlink()
        return True

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_ACTUAL.write_text(
        json.dumps(a, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    DEBUG_EXPECTED.write_text(
        json.dumps(b, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return False


def _write_snapshot(data: dict[str, Any]) -> None:
    """Write the normalized snapshot to disk with stable formatting."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    if not txt.endswith("\n"):
        txt += "\n"  # enforce trailing newline for clean diffs
    SNAPSHOT_PATH.write_text(txt, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.anyio
def test_openapi_snapshot_contract_is_stable() -> None:
    """Fetch, normalize, and compare OpenAPI against the committed snapshot.

    Behavior:
        - If UPDATE_OPENAPI_SNAPSHOT=1 is set, writes the current normalized
          spec to disk and passes (intentional change).
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
        "Run with UPDATE_OPENAPI_SNAPSHOT=1 to create or update the snapshot."
    )

    with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
        snap = cast(dict[str, Any], json.load(f))

    assert _json_equal(normalized, snap), (
        "OpenAPI contract drift detected. If this change is intentional, "
        "update the snapshot with UPDATE_OPENAPI_SNAPSHOT=1. Otherwise, "
        "reconcile your routers/schemas to match the published contract. "
        f"Debug written to {DEBUG_ACTUAL} (actual) and {DEBUG_EXPECTED} (snapshot)."
    )


@pytest.mark.anyio
def test_openapi_includes_canonical_envelopes() -> None:
    """Assert canonical envelopes exist in components/schemas.

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

    # Minimal shape checks to prevent accidental field renames.
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
