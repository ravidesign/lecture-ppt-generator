from __future__ import annotations

from pathlib import Path

from core.ppt_generator import LEGACY_THEME_PRESET_MAP, PRESETS


THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"


def resolve_preset_id(preset_id: str) -> str:
    return LEGACY_THEME_PRESET_MAP.get(preset_id, preset_id or "corporate")


def preset_name(preset_id: str) -> str:
    resolved = resolve_preset_id(preset_id)
    return PRESETS.get(resolved, PRESETS["corporate"])["name"]


def theme_markdown_path(preset_id: str) -> Path:
    resolved = resolve_preset_id(preset_id)
    return THEMES_DIR / f"{resolved}.md"


def load_theme_markdown(preset_id: str) -> str:
    path = theme_markdown_path(preset_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def preset_metadata(preset_id: str) -> dict:
    resolved = resolve_preset_id(preset_id)
    preset = PRESETS.get(resolved, PRESETS["corporate"])
    colors = preset["colors"]
    return {
        "id": resolved,
        "name": preset["name"],
        "desc": preset["desc"],
        "swatch": {
            "header": "#{:02X}{:02X}{:02X}".format(*colors["header"]),
            "accent": "#{:02X}{:02X}{:02X}".format(*colors["accent"]),
            "bg": "#{:02X}{:02X}{:02X}".format(*colors["bg"]),
        },
        "header_style": preset["header_style"],
        "bullet_style": preset["bullet_style"],
        "density": preset["density"],
        "theme_doc_path": str(theme_markdown_path(resolved)),
        "theme_markdown": load_theme_markdown(resolved),
    }


def list_theme_specs() -> list[dict]:
    return [preset_metadata(preset_id) for preset_id in PRESETS.keys()]
