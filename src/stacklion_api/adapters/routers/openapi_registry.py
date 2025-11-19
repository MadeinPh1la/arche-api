# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
OpenAPI Contract Registry Injector (Adapters Layer)

Purpose:
    Ensure canonical envelopes (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope)
    are present under components/schemas even if no routes reference them yet.

Why:
    FastAPI emits only referenced schemas. Our CI snapshot requires the envelopes to
    exist at all times, so this injector amends the OpenAPI schema during generation.

Safety:
    • Does not add routes or change endpoint behavior.
    • Idempotent and cache-friendly via FastAPI's `app.openapi_schema`.

Layer:
    adapters/routers
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import cast

from fastapi import FastAPI
from pydantic import BaseModel

from stacklion_api.adapters.schemas.http import (
    ErrorEnvelope,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.types import JsonValue

# Use non-literal names so Ruff won't rewrite setattr(...) to dot-assignments.
OPENAPI_SCHEMA_ATTR = "openapi_schema"
OPENAPI_ATTR = "openapi"


def _schema_name(model: type[BaseModel]) -> str:
    """Return the OpenAPI schema name for a Pydantic v2 model.

    Prefers an explicit title via `model_config` and falls back to the class name.
    """
    cfg: Mapping[str, object] = getattr(model, "model_config", {})
    title = cfg.get("title") if isinstance(cfg, Mapping) else None
    return str(title) if title else model.__name__


def _model_schema(model: type[BaseModel]) -> dict[str, JsonValue]:
    """Return the JSON Schema for a Pydantic v2 model with stable refs."""
    return cast(
        dict[str, JsonValue],
        model.model_json_schema(ref_template="#/components/schemas/{model}"),
    )


def attach_openapi_contract_registry(app: FastAPI) -> None:
    """Inject canonical envelopes into `components/schemas` at OpenAPI build time.

    This wraps the app's `openapi()` to:

        1) Build the baseline schema via the original generator.
        2) Register the canonical envelopes if they are absent.
        3) Cache the result on `app.openapi_schema`.
    """
    original_openapi = app.openapi

    def _custom_openapi() -> dict[str, JsonValue]:
        # Reuse cached schema if present.
        existing = cast(dict[str, JsonValue] | None, getattr(app, OPENAPI_SCHEMA_ATTR, None))
        if existing is not None:
            return existing

        # Build baseline schema via FastAPI's generator.
        base = cast(dict[str, JsonValue], original_openapi())

        # Ensure components/schemas exists.
        components = cast(
            MutableMapping[str, JsonValue],
            base.setdefault("components", cast(JsonValue, {})),
        )
        schemas = cast(
            MutableMapping[str, JsonValue],
            components.setdefault("schemas", cast(JsonValue, {})),
        )

        # Register canonical envelopes if missing.
        for model in (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope):
            name = _schema_name(model)
            if name not in schemas:
                s = _model_schema(model)
                # pydantic v2 may include local $defs; remove to avoid bloating components.
                s.pop("$defs", None)
                schemas[name] = s

        # Cache and return.
        setattr(app, OPENAPI_SCHEMA_ATTR, base)
        return base

    # mypy-safe override without triggering method-assign issues.
    setattr(app, OPENAPI_ATTR, _custom_openapi)
