"""Project-wide JSON typing helpers.

These aliases model JSON-serializable values and are safe to use in public
envelopes and presenter signatures.
"""

from __future__ import annotations

type JsonPrimitive = None | bool | int | float | str
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]

__all__ = ["JsonPrimitive", "JsonValue"]
