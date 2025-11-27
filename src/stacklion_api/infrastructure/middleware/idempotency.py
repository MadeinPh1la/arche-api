# src/stacklion_api/infrastructure/middleware/idempotency.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""HTTP Idempotency Middleware.

Purpose:
    Provide reusable HTTP idempotency for write operations (POST/PUT/PATCH/DELETE)
    using a DB-backed dedupe store.

Layer:
    infrastructure

Behavior:
    Idempotency is opt-in per client: if `Idempotency-Key` is absent, the request
    passes through unchanged. If the header is present, deterministic behavior
    is enforced:

        * Same key + same request → same response.
        * Same key + different request → 409 conflict.
        * In-flight requests with same key → 409 "in progress".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Collection
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from stacklion_api.adapters.repositories.idempotency_repository import IdempotencyRepository
from stacklion_api.adapters.schemas.http.envelopes import ErrorEnvelope, ErrorObject
from stacklion_api.infrastructure.database.session import get_db_session


def _utcnow_naive() -> datetime:
    """Return a naive datetime representing current UTC time.

    DB columns for idempotency use TIMESTAMP WITHOUT TIME ZONE, so we must
    consistently use naive datetimes here.
    """
    return datetime.utcnow()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """ASGI middleware implementing idempotency for write operations.

    The middleware:

        * Applies only to configured HTTP methods (default: POST, PUT, PATCH, DELETE).
        * Treats requests without `Idempotency-Key` as non-idempotent and passes
          them through unchanged.
        * For requests with `Idempotency-Key`:
            - Reads and hashes the request to compute a deterministic request hash.
            - Uses the idempotency repository to:
                + Replay completed responses with matching hash.
                + Reject conflicting payloads with a 409 error.
                + Reject concurrent in-progress requests with a 409 error.
            - For first-time or expired keys, creates a STARTED record and stores
              the final response payload once completed.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        ttl_seconds: int = 60 * 60 * 24,
        methods: Collection[str] | None = None,
        session_provider: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: Downstream ASGI application.
            ttl_seconds: TTL window in seconds for idempotency keys.
            methods: HTTP methods to apply idempotency to; defaults to
                {POST, PUT, PATCH, DELETE}.
            session_provider: Async context manager factory that yields an
                `AsyncSession`. Defaults to :func:`get_db_session`.
        """
        super().__init__(app)
        self._ttl_seconds = int(ttl_seconds)
        self._methods = {m.upper() for m in (methods or {"POST", "PUT", "PATCH", "DELETE"})}
        self._session_provider = session_provider or get_db_session

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Dispatch the request through idempotency logic or directly downstream."""
        method = request.method.upper()
        if method not in self._methods:
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            # No header → behave as normal, non-idempotent request.
            return await call_next(request)

        # Buffer the request body so we can both hash it and re-send to downstream.
        raw_body = await request.body()

        async def receive() -> dict[str, Any]:
            """Return the buffered request body to downstream handlers."""
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request = Request(request.scope, receive=receive)

        request_hash = self._compute_request_hash(request, raw_body)
        trace_id = request.headers.get("X-Request-ID")

        async with self._session_provider() as session:
            repo = IdempotencyRepository(session)
            now = _utcnow_naive()

            existing = await repo.get_active(key, now=now)
            if existing is not None:
                if existing.request_hash != request_hash:
                    return self._conflict_response(
                        code="IDEMPOTENCY_KEY_CONFLICT",
                        message="Idempotency-Key reused with a different request payload.",
                        trace_id=trace_id,
                    )
                if existing.state == "COMPLETED" and existing.status_code is not None:
                    # Replay stored response.
                    if existing.response_body is None:
                        return Response(status_code=existing.status_code)
                    return JSONResponse(
                        status_code=existing.status_code,
                        content=dict(existing.response_body),
                    )
                # Record is STARTED but not completed within TTL or still in-flight.
                return self._conflict_response(
                    code="IDEMPOTENCY_KEY_IN_PROGRESS",
                    message="Another request with the same Idempotency-Key is in progress.",
                    trace_id=trace_id,
                )

            # No active record → create STARTED and proceed to downstream handler.
            started_record = await repo.create_started(
                key=key,
                request_hash=request_hash,
                method=method,
                path=request.url.path,
                ttl_seconds=self._ttl_seconds,
                now=now,
            )

            response = await call_next(request)
            body_bytes = await self._consume_response_body(response)

            response_body: dict[str, Any] | None
            try:
                response_body = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
            except json.JSONDecodeError:
                response_body = None

            await repo.save_result(
                started_record,
                status_code=response.status_code,
                response_body=response_body,
                now=_utcnow_naive(),
            )

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

    @staticmethod
    def _compute_request_hash(request: Request, body: bytes) -> str:
        """Compute a deterministic hash for the given request and body."""
        method = request.method.upper()
        path = request.url.path
        query_pairs = "&".join(f"{k}={v}" for k, v in sorted(request.query_params.multi_items()))
        body_digest = hashlib.sha256(body).hexdigest()
        material = f"{method}|{path}|{query_pairs}|{body_digest}".encode()
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    async def _consume_response_body(response: Any) -> bytes:
        """Consume and buffer the response body from a Response-like object.

        Notes:
            * For typical JSON responses, FastAPI stores the body on ``response.body``.
            * For streaming responses, we fall back to consuming an async iterator
              if a ``body_iterator`` attribute is present.
        """
        raw_body = getattr(response, "body", None)
        if isinstance(raw_body, (bytes, bytearray)):
            return bytes(raw_body)
        if isinstance(raw_body, str):
            return raw_body.encode("utf-8")

        body_iter = getattr(response, "body_iterator", None)
        if body_iter is None:
            return b""

        body_chunks: list[bytes] = []
        async for chunk in body_iter:
            body_chunks.append(chunk)
        body_bytes = b"".join(body_chunks)

        async def iterator() -> AsyncIterator[bytes]:
            yield body_bytes

        # Reset iterator for any downstream consumer.
        response.body_iterator = iterator()
        return body_bytes

    @staticmethod
    def _conflict_response(code: str, message: str, *, trace_id: str | None) -> JSONResponse:
        """Build a canonical 409 ErrorEnvelope response."""
        error = ErrorObject(
            code=code,
            http_status=status.HTTP_409_CONFLICT,
            message=message,
            details={},
            trace_id=trace_id,
        )
        envelope = ErrorEnvelope(error=error)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope.model_dump(),
        )
