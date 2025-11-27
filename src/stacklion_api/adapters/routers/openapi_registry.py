# src/stacklion_api/adapters/routers/openapi_registry.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""OpenAPI Contract Registry Injector (Adapters Layer).

Purpose:
    Ensure canonical envelopes (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope)
    are always present under `components/schemas` in the generated OpenAPI.

Design:
    FastAPI normally emits schemas only when referenced. CI enforces a stable
    snapshot where envelopes must always exist. This module wraps FastAPI's
    OpenAPI generator to inject them deterministically.

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

OPENAPI_SCHEMA_ATTR = "openapi_schema"
OPENAPI_ATTR = "openapi"


def _schema_name(model: type[BaseModel]) -> str:
    """Return the OpenAPI schema name for a Pydantic v2 model."""
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
    """Inject canonical envelopes into the OpenAPI schema.

    This wraps the application's `openapi()` method with a caching injector
    that ensures envelope schemas are present even when unused.
    """
    original_openapi = app.openapi

    def _custom_openapi() -> dict[str, JsonValue]:
        cached = cast(dict[str, JsonValue] | None, getattr(app, OPENAPI_SCHEMA_ATTR, None))
        if cached is not None:
            return cached

        base = cast(dict[str, JsonValue], original_openapi())
        components = cast(
            MutableMapping[str, JsonValue],
            base.setdefault("components", cast(JsonValue, {})),
        )
        schemas = cast(
            MutableMapping[str, JsonValue],
            components.setdefault("schemas", cast(JsonValue, {})),
        )

        for model in (SuccessEnvelope, PaginatedEnvelope, ErrorEnvelope):
            name = _schema_name(model)
            if name not in schemas:
                schema = _model_schema(model)
                schema.pop("$defs", None)
                schemas[name] = schema

        setattr(app, OPENAPI_SCHEMA_ATTR, base)
        return base

    setattr(app, OPENAPI_ATTR, _custom_openapi)
