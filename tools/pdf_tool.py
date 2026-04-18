from __future__ import annotations

import re

import fitz

from core.pdf_parser import build_page_plan_preview, format_page_ranges


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


def build_page_source_excerpt(page_texts: list[dict], max_pages: int = 10, max_chars_per_page: int = 1200) -> str:
    parts = []
    for row in page_texts[:max_pages]:
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        if max_chars_per_page and len(text) > max_chars_per_page:
            text = text[:max_chars_per_page].rstrip() + "..."
        parts.append(f"[Page {row.get('page')}]\n{text}")
    return "\n\n".join(parts).strip()
