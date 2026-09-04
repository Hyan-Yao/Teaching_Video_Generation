"""Native Code2Video theme normalization.

TeachGen passes a plain dictionary through ``RunConfig``.  Keeping this module free
of TeachGen imports also lets the standalone Code2Video entry point use the same
light theme by default.
"""

from __future__ import annotations

from typing import Mapping


SHARED_LIGHT_THEME = {
    "name": "shared-light",
    "background": "#F7F6F0",
    "primary": "#1B3A6B",
    "secondary": "#0F766E",
    "highlight": "#9A6700",
    "body": "#2A2A2A",
    "panel": "#E4E0D5",
    "grid": "#E4E0D5",
}

REQUIRED_KEYS = frozenset(SHARED_LIGHT_THEME)


def normalize_theme(theme: Mapping | None = None) -> dict:
    """Validate and copy a serializable palette, defaulting to shared light."""
    normalized = dict(SHARED_LIGHT_THEME if theme is None else theme)
    missing = REQUIRED_KEYS - normalized.keys()
    if missing:
        raise ValueError(f"Code2Video theme is missing fields: {sorted(missing)}")
    for key in REQUIRED_KEYS - {"name"}:
        value = normalized[key]
        if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
            raise ValueError(f"invalid theme color {key}={value!r}")
        int(value[1:], 16)
        normalized[key] = value.upper()
    return normalized
