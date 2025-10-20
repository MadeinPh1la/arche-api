from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

scheme = HTTPBearer(auto_error=False)


def jwt_secret() -> str:
    s = os.getenv("AUTH_HS256_SECRET", "") or ""
    return s


def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(scheme),  # noqa: B008
) -> None:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        jwt.decode(creds.credentials, jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        # Hide decode internals; keep traceback provenance clean
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None
