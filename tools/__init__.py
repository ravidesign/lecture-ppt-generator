from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "extract_selected_page_texts": ("tools.pdf_tool", "extract_selected_page_texts"),
    "build_page_plan_bundle": ("tools.pdf_tool", "build_page_plan_bundle"),
    "build_page_summary": ("tools.pdf_tool", "build_page_summary"),
    "build_preview_headings": ("tools.pdf_tool", "build_preview_headings"),
    "build_page_source_excerpt": ("tools.pdf_tool", "build_page_source_excerpt"),
    "extract_image_assets": ("tools.pdf_tool", "extract_image_assets"),
    "write_slides_from_pdf": ("tools.slide_tool", "write_slides_from_pdf"),
    "design_curriculum_fallback": ("tools.slide_tool", "design_curriculum_fallback"),
    "fact_check_fallback": ("tools.slide_tool", "fact_check_fallback"),
    "generate_exam_fallback": ("tools.slide_tool", "generate_exam_fallback"),
    "review_questions_fallback": ("tools.slide_tool", "review_questions_fallback"),
    "apply_layout_design": ("tools.slide_tool", "apply_layout_design"),
    "build_exam_summary": ("tools.slide_tool", "build_exam_summary"),
    "resolve_preset_id": ("tools.theme_tool", "resolve_preset_id"),
    "preset_name": ("tools.theme_tool", "preset_name"),
    "preset_metadata": ("tools.theme_tool", "preset_metadata"),
    "load_theme_markdown": ("tools.theme_tool", "load_theme_markdown"),
    "list_theme_specs": ("tools.theme_tool", "list_theme_specs"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
