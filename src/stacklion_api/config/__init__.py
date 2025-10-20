"""
Config package export.

Keeps import sites clean and stable:
    from src.config import get_settings, Settings
"""

from __future__ import annotations

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
