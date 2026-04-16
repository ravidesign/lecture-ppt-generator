from __future__ import annotations

import re
from copy import deepcopy

from core.pdf_parser import format_page_ranges, parse_page_range


PROCESS_KEYWORDS = (
    "process",
    "workflow",
    "pipeline",
    "roadmap",
    "step",
    "steps",
    "procedure",
    "flow",
    "단계",
    "절차",
    "흐름",
    "프로세스",
    "과정",
    "순서",
)
COMPARE_KEYWORDS = (
    "compare",
    "comparison",
    "vs",
    "versus",
    "before",
    "after",
    "difference",
    "비교",
    "차이",
    "장단점",
    "대조",
)
CASE_KEYWORDS = (
    "case",
    "example",
    "demo",
    "scenario",
    "사례",
    "예시",
    "실습",
    "데모",
    "적용",
)
DATA_KEYWORDS = (
    "data",
    "metric",
    "metrics",
    "result",
    "results",
    "figure",
    "chart",
    "table",
    "통계",
    "지표",
    "데이터",
    "결과",
    "수치",
    "표",
    "그래프",
)
STEP_PREFIX_RE = re.compile(
    r"^\s*(?:\d+[\.\)]|step\s*\d+|phase\s*\d+|첫째|둘째|셋째|넷째|다섯째|1단계|2단계|3단계|4단계)\s*[:.\-]?\s*",
    re.IGNORECASE,
)
MULTISPACE_RE = re.compile(r"\s+")


def _clean_text(value) -> str:
    text = str(value or "").strip()
    return MULTISPACE_RE.sub(" ", text)


def _dedupe_points(points: list[str], limit: int = 5) -> list[str]:
    seen = set()
    result = []
    for point in points:
        cleaned = _clean_text(point)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _normalize_source_pages(value: str, selected_pages: list[int] | None) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    max_page = max(selected_pages or [0])
    pages = parse_page_range(text, max_page) if max_page else []
    if pages:
        return format_page_ranges(pages)
    return text


def _fallback_source_pages(content_index: int, total_content: int, selected_pages: list[int] | None) -> str:
    pages = list(selected_pages or [])
    if not pages:
        return ""
    if total_content <= 1:
        return format_page_ranges(pages[: min(len(pages), 6)])

    chunk = max(1, round(len(pages) / total_content))
    start = min(content_index * chunk, max(len(pages) - 1, 0))
    end = min(len(pages), start + chunk + 1)
    return format_page_ranges(pages[start:end])


def infer_content_kind(slide: dict) -> str:
    title = _clean_text(slide.get("title")).lower()
    subtitle = _clean_text(slide.get("subtitle")).lower()
    points = [_clean_text(point).lower() for point in slide.get("points", []) if _clean_text(point)]
    merged = " ".join([title, subtitle, *points])

    if any(keyword in merged for keyword in PROCESS_KEYWORDS):
        return "process"
    if any(keyword in merged for keyword in COMPARE_KEYWORDS):
        return "compare"
    if any(keyword in merged for keyword in CASE_KEYWORDS):
        return "case"
    if any(keyword in merged for keyword in DATA_KEYWORDS):
        return "data"

    if points and sum(1 for point in points if STEP_PREFIX_RE.match(point)) >= max(2, len(points) - 1):
        return "process"

    if " vs " in title or " 대 " in title or title.count("/") == 1:
        return "compare"

    if len(points) >= 4 and sum(1 for point in points if len(point) <= 28) >= 3:
        return "data"

    return "explain"


def _derive_compare_payload(slide: dict) -> dict:
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    title = _clean_text(slide.get("title"))
    left_title = "핵심 A"
    right_title = "핵심 B"

    title_match = re.split(r"\s+vs\.?\s+|\s+VS\.?\s+| 비교 | 대 ", title)
    if len(title_match) == 2:
        left_title = _clean_text(title_match[0]) or left_title
        right_title = _clean_text(title_match[1]) or right_title

    midpoint = max(1, len(points) // 2)
    left_points = points[:midpoint]
    right_points = points[midpoint:] or points[:2]
    return {
        "compare_left_title": left_title,
        "compare_right_title": right_title,
        "compare_left_points": left_points[:3],
        "compare_right_points": right_points[:3],
    }


def _derive_process_payload(slide: dict) -> dict:
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    cleaned = [STEP_PREFIX_RE.sub("", point).strip() for point in points]
    return {"diagram_steps": [step for step in cleaned if step][:4]}


def _ensure_notes(slide: dict) -> str:
    notes = _clean_text(slide.get("notes"))
    if notes:
        return notes
    title = _clean_text(slide.get("title")) or "이 슬라이드"
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    if points:
        return f"{title}에서는 {points[0]}을 중심으로 설명하고, 이어서 핵심 포인트를 연결합니다."
    return f"{title}의 핵심 메시지를 짧고 분명하게 전달합니다."


def _kind_layout(kind: str, slide: dict) -> str:
    existing = _clean_text(slide.get("layout")).lower()
    if existing and existing not in {"auto", ""}:
        return existing
    if kind == "process":
        return "process"
    if kind == "compare":
        return "compare"
    if kind == "case":
        return "split"
    if kind == "data":
        return "card" if len(slide.get("points", [])) >= 4 else "highlight"
    return existing or "auto"


def build_outline(slides: list[dict]) -> list[dict]:
    outline = []
    for index, slide in enumerate(slides, start=1):
        outline.append(
            {
                "index": index,
                "type": slide.get("type", "content"),
                "title": slide.get("title", ""),
                "subtitle": slide.get("subtitle", ""),
                "layout": slide.get("layout", ""),
                "content_kind": slide.get("content_kind", ""),
                "source_pages": slide.get("source_pages", ""),
                "point_count": len(slide.get("points", []) or slide.get("items", []) or []),
                "has_image": bool(slide.get("image_asset_name")),
                "image_page": slide.get("image_page"),
            }
        )
    return outline


def build_quality_summary(slides: list[dict]) -> dict:
    warnings = []
    content_slides = [slide for slide in slides if slide.get("type", "content") == "content"]
    missing_sources = sum(1 for slide in content_slides if not slide.get("source_pages"))
    missing_images = sum(1 for slide in content_slides if not slide.get("image_asset_name"))
    process_count = sum(1 for slide in content_slides if slide.get("content_kind") == "process")
    compare_count = sum(1 for slide in content_slides if slide.get("content_kind") == "compare")
    dense_slides = 0
    long_point_slides = 0
    notes_missing = 0
    seen_titles = {}
    duplicate_titles = 0
    kind_counts = {"process": 0, "compare": 0, "case": 0, "data": 0, "explain": 0}

    for slide in content_slides:
        title_key = _clean_text(slide.get("title")).lower()
        if title_key:
            seen_titles[title_key] = seen_titles.get(title_key, 0) + 1

        points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
        if len(points) >= 5 or sum(len(point) for point in points) >= 240:
            dense_slides += 1
        if any(len(point) >= 72 for point in points):
            long_point_slides += 1
        if not _clean_text(slide.get("notes")):
            notes_missing += 1

        kind = slide.get("content_kind") or "explain"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    duplicate_titles = sum(count - 1 for count in seen_titles.values() if count > 1)

    if missing_sources:
        warnings.append(f"근거 페이지가 비어 있는 내용 슬라이드 {missing_sources}장")
    if missing_images:
        warnings.append(f"PDF 이미지가 직접 연결되지 않은 내용 슬라이드 {missing_images}장")
    if dense_slides:
        warnings.append(f"텍스트 밀도가 높은 내용 슬라이드 {dense_slides}장")
    if long_point_slides:
        warnings.append(f"문장이 긴 포인트가 포함된 슬라이드 {long_point_slides}장")
    if duplicate_titles:
        warnings.append(f"제목이 겹치는 슬라이드 {duplicate_titles}장")
    if notes_missing:
        warnings.append(f"발표자 노트가 비어 있는 내용 슬라이드 {notes_missing}장")

    return {
        "content_count": len(content_slides),
        "process_count": process_count,
        "compare_count": compare_count,
        "missing_sources": missing_sources,
        "missing_images": missing_images,
        "dense_slides": dense_slides,
        "long_point_slides": long_point_slides,
        "duplicate_titles": duplicate_titles,
        "notes_missing": notes_missing,
        "kind_counts": kind_counts,
        "warnings": warnings,
    }


def review_slides(slides_data: list[dict], selected_pages: list[int] | None = None) -> dict:
    slides = deepcopy(slides_data or [])
    content_total = sum(1 for slide in slides if slide.get("type", "content") == "content")
    content_index = 0

    for slide in slides:
        slide_type = slide.get("type", "content")

        if slide_type == "agenda":
            slide["items"] = _dedupe_points(list(slide.get("items", [])), limit=8)
            slide["title"] = _clean_text(slide.get("title")) or "목차"
            continue

        if slide_type == "summary":
            slide["points"] = _dedupe_points(list(slide.get("points", [])), limit=6)
            slide["title"] = _clean_text(slide.get("title")) or "핵심 요약"
            continue

        if slide_type == "title":
            slide["title"] = _clean_text(slide.get("title")) or "강의 교안"
            slide["subtitle"] = _clean_text(slide.get("subtitle"))
            continue

        content_index += 1
        slide["title"] = _clean_text(slide.get("title")) or f"핵심 내용 {content_index}"
        slide["subtitle"] = _clean_text(slide.get("subtitle"))
        slide["points"] = _dedupe_points(list(slide.get("points", [])), limit=5)
        slide["content_kind"] = infer_content_kind(slide)
        slide["layout"] = _kind_layout(slide["content_kind"], slide)
        slide["source_pages"] = _normalize_source_pages(slide.get("source_pages"), selected_pages)
        if not slide["source_pages"]:
            slide["source_pages"] = _fallback_source_pages(content_index - 1, content_total, selected_pages)
        slide["notes"] = _ensure_notes(slide)

        if slide["content_kind"] == "process":
            slide.update(_derive_process_payload(slide))
        elif slide["content_kind"] == "compare":
            slide.update(_derive_compare_payload(slide))

    return {
        "slides": slides,
        "outline": build_outline(slides),
        "quality": build_quality_summary(slides),
    }
