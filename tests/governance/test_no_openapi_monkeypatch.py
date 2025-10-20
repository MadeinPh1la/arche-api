from __future__ import annotations

import pathlib
import re

FORBIDDEN = re.compile(r"\bapp\.openapi\s*=", re.IGNORECASE)
CODE_ROOT = pathlib.Path(__file__).resolve().parents[2]  # repo root
SRC = CODE_ROOT / "src"


def test_no_openapi_monkeypatch() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if FORBIDDEN.search(text):
            offenders.append(str(path.relative_to(CODE_ROOT)))
    assert not offenders, (
        "Forbidden OpenAPI monkey-patch detected:\n  - "
        + "\n  - ".join(offenders)
        + "\nUse the contract registry injector instead "
        + "(attach_openapi_contract_registry)."
    )
