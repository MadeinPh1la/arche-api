from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_cold_start_imports_clean() -> None:
    # Ensure 'src/' is importable
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    # Reset Prometheus default registry to avoid duplicate registration on re-import
    import prometheus_client as prom  # local import to avoid early binding

    prom.REGISTRY = prom.CollectorRegistry()

    # Purge cached modules for a clean import
    for name in list(sys.modules):
        if name.startswith("arche_api"):
            sys.modules.pop(name)

    app_mod = importlib.import_module("arche_api.main")
    create_app = app_mod.create_app
    assert callable(create_app)
    app = create_app()
    assert app is not None
