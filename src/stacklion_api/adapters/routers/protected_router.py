# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Protected Router (feature-flagged auth): ``/v1/protected``.

Minimal protected surface used by integration tests to verify HS256-based
authentication and the ``AUTH_ENABLED`` toggle. When ``AUTH_ENABLED=false``,
access is permitted without a token; when true, a valid HS256 token is required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.infrastructure.auth.jwt_dependency import auth_required

# Dependency instance (no per-call construction; avoids B008 in defaults).
AUTH_DEP = auth_required()

router = BaseRouter(version="v1", resource="protected", tags=["Auth"])
_api = APIRouter(prefix="/v1/protected", tags=["Auth"])

# Explicit ErrorEnvelope content to guarantee schema inclusion in the snapshot.
_ERROR_JSON_CONTENT = {
    "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
}


@_api.get(
    "/ping",
    summary="Auth check ping",
    description="Returns 200 when reachable. Requires valid bearer token when AUTH_ENABLED=true.",
    # Intentionally omit a 200 response_model to match snapshot (description-only).
    responses={
        200: {"description": "OK"},
        401: {
            "description": "Unauthorized (missing/invalid auth)",
            "content": _ERROR_JSON_CONTENT,
        },
        403: {
            "description": "Forbidden (insufficient permissions)",
            "content": _ERROR_JSON_CONTENT,
        },
    },
    # Apply dependency at operation level to avoid B008 on function defaults.
    dependencies=[Depends(AUTH_DEP)],
)
def ping() -> dict[str, str]:
    """Return a simple OK payload.

    Returns:
        dict[str, str]: {"status": "ok"} on success (401/403 are produced by the dependency).
    """
    return {"status": "ok"}


def get_router() -> APIRouter:
    """Expose the inner APIRouter for inclusion in the FastAPI app."""
    return _api
