from __future__ import annotations

import re

import fitz

from core.pdf_parser import build_page_plan_preview, extract_pdf_images, format_page_ranges


def extract_selected_page_texts(pdf_path: str, selected_pages: list[int]) -> list[dict]:
    pages = sorted({int(page) for page in selected_pages if int(page) >= 1})
    if not pages:
        return []
    doc = fitz.open(pdf_path)
    try:
        rows = []
        for page_no in pages:
            page = doc.load_page(page_no - 1)
            text = page.get_text("text") or ""
            rows.append({"page": page_no, "text": text.strip()})
        return rows
    finally:
        doc.close()


def build_page_summary(selected_pages: list[int]) -> str:
    return format_page_ranges(selected_pages)


def build_preview_headings(pdf_path: str, page_plan: dict) -> list[dict]:
    preview = build_page_plan_preview(pdf_path, page_plan)
    return preview.get("headings", [])


def build_page_plan_bundle(pdf_path: str, page_plan: dict) -> dict:
    preview = build_page_plan_preview(pdf_path, page_plan)
    return {
        "page_summary": preview.get("page_summary", ""),
        "headings": preview.get("headings", []),
        "selection_note": page_plan.get("selection_note", ""),
        "selected_pages": page_plan.get("selected_pages", []),
    }


def extract_image_assets(pdf_path: str, page_plan: dict, asset_dir: str, max_images: int = 20) -> list[dict]:
    return extract_pdf_images(
        pdf_path,
        asset_dir,
        selected_pages=page_plan.get("selected_pages", []),
        max_images=max_images,
    )


def build_page_source_excerpt(page_texts: list[dict], max_pages: int = 10, max_chars_per_page: int = 1200) -> str:
    parts = []
    for row in page_texts[:max_pages]:
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if max_chars_per_page and len(text) > max_chars_per_page:
            text = text[:max_chars_per_page].rstrip() + "..."
        parts.append(f"[Page {row.get('page')}]\n{text}")
    return "\n\n".join(parts).strip()
