from __future__ import annotations

# Re-export Principal from the actual module file in this package.
# If you later split files (principal.py), you can switch the import target here.
from .value_objects import Principal

__all__ = ["Principal"]
