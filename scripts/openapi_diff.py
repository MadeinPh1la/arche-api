#!/usr/bin/env python3
import difflib
import json
from pathlib import Path

from tests.openapi.test_openapi_snapshot import SNAPSHOT_PATH, _fetch_openapi, _normalize_openapi

cur = _normalize_openapi(_fetch_openapi())
cur_s = json.dumps(cur, sort_keys=True, separators=(",", ":")).splitlines()
snap_s = Path(SNAPSHOT_PATH).read_text(encoding="utf-8").splitlines()

diff = "\n".join(difflib.unified_diff(snap_s, cur_s, fromfile="snapshot", tofile="current", n=2))
print(diff)
