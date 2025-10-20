import datetime as dt
from collections.abc import Iterator

import jwt
import pytest
from starlette.testclient import TestClient

from stacklion_api.main import create_app


@pytest.fixture(autouse=True)
def _env_isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Minimal CI/dev-friendly defaults
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    yield


def _token(secret: str, minutes: int = 5) -> str:
    now = dt.datetime.utcnow()
    return jwt.encode(
        {"sub": "u1", "iat": now, "exp": now + dt.timedelta(minutes=minutes)},
        secret,
        algorithm="HS256",
    )


def _client() -> TestClient:
    app = create_app()  # reads env each time
    return TestClient(app)


def test_missing_token_yields_401_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "test-secret")
    client = _client()

    r = client.get("/v1/protected/ping")  # no Authorization header
    assert r.status_code == 401
    assert r.json()["detail"] in {"Missing bearer token", "Missing token", "Invalid token"}


def test_valid_hs256_token_yields_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "test-secret")
    client = _client()

    tok = _token("test-secret")
    r = client.get("/v1/protected/ping", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_disabled_allows_access_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    client = _client()
    r = client.get("/v1/protected/ping")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
