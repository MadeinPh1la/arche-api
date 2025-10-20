from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stacklion_api.main import app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"


def main() -> None:
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()

    # keep it aligned with test normalization
    spec.pop("servers", None)
    spec.pop("externalDocs", None)
    if isinstance(spec.get("info"), dict):
        spec["info"] = {k: v for k, v in spec["info"].items() if not str(k).startswith("x-")}

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    main()
