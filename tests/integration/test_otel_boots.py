# tests/integration/test_otel_boots.py
import importlib
import os

import pytest


@pytest.mark.anyio
async def test_app_boots_with_otel_disabled() -> None:
    os.environ.pop("OTEL_ENABLED", None)
    mod = importlib.import_module("arche_api.main")
    app = mod.app
    assert getattr(app, "title", None)


@pytest.mark.anyio
async def test_app_boots_with_otel_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "true")
    mod = importlib.reload(importlib.import_module("arche_api.main"))
    app = mod.app
    assert getattr(app, "title", None)
