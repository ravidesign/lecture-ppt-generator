from __future__ import annotations

from core.ppt_generator import LEGACY_THEME_PRESET_MAP, PRESETS


def resolve_preset_id(preset_id: str) -> str:
    return LEGACY_THEME_PRESET_MAP.get(preset_id, preset_id or "corporate")


def preset_name(preset_id: str) -> str:
    resolved = resolve_preset_id(preset_id)
    return PRESETS.get(resolved, PRESETS["corporate"])["name"]
