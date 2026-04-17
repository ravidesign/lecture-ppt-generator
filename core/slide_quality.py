from __future__ import annotations

import hashlib
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
SECTION_WORDS = (
    "개요",
    "구조",
    "기능",
    "분류",
    "종류",
    "비교",
    "요약",
    "핵심",
    "기전",
    "원리",
)
STEP_PREFIX_RE = re.compile(
    r"^\s*(?:\d+[\.\)]|step\s*\d+|phase\s*\d+|첫째|둘째|셋째|넷째|다섯째|1단계|2단계|3단계|4단계)\s*[:.\-]?\s*",
    re.IGNORECASE,
)
MULTISPACE_RE = re.compile(r"\s+")
VALID_LAYOUTS = {
    "auto",
    "classic",
    "split",
    "card",
    "highlight",
    "process",
    "compare",
    "image_left",
    "image_top",
    "chapter",
}
VALID_ROLES = {"title", "toc", "content", "chapter", "summary"}
VALID_IMAGE_MODES = {"hero", "support", "none"}
VALID_IMAGE_CHOICE_MODES = {"auto", "manual", "manual_none"}


def _clean_text(value) -> str:
    text = str(value or "").strip()
    return MULTISPACE_RE.sub(" ", text)


def _dedupe_points(points: list[str], limit: int = 6) -> list[str]:
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


def _normalize_role(slide: dict) -> str:
    slide_type = str(slide.get("type", "content") or "content").strip().lower()
    if slide_type == "title":
        return "title"
    if slide_type == "agenda":
        return "toc"
    if slide_type == "summary":
        return "summary"

    role = _clean_text(slide.get("role")).lower()
    if role in VALID_ROLES:
        return role
    return "content"


def _normalize_layout(value) -> str:
    layout = _clean_text(value).lower()
    return layout if layout in VALID_LAYOUTS else "auto"


def _normalize_image_mode(value) -> str:
    mode = _clean_text(value).lower()
    return mode if mode in VALID_IMAGE_MODES else "none"


def _normalize_image_choice_mode(value) -> str:
    mode = _clean_text(value).lower()
    return mode if mode in VALID_IMAGE_CHOICE_MODES else "auto"


def _normalize_source_page_list(source_pages: str) -> list[int]:
    page_numbers = [int(match) for match in re.findall(r"\d+", str(source_pages or ""))]
    if not page_numbers:
        return []
    max_page = max(page_numbers)
    parsed = parse_page_range(str(source_pages or ""), max_page)
    return parsed or sorted(set(page_numbers))


def _safe_hash(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:8]


def _infer_section_title(slide: dict) -> str:
    existing = _clean_text(slide.get("section_title"))
    if existing:
        return existing

    title = _clean_text(slide.get("title"))
    subtitle = _clean_text(slide.get("subtitle"))
    if title and any(word in title for word in SECTION_WORDS):
        chunks = re.split(r"[:\-|/]", title)
        if chunks:
            return _clean_text(chunks[0]) or title

    if subtitle and len(subtitle) <= 36:
        return title

    return ""


def infer_content_kind(slide: dict) -> str:
    if _normalize_role(slide) == "chapter":
        return "chapter"

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


def _measure_density(slide: dict) -> dict:
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    total_chars = sum(len(point) for point in points)
    max_len = max([len(point) for point in points], default=0)
    short_points = sum(1 for point in points if len(point) <= 36)
    point_count = len(points)
    dense = (
        point_count >= 5
        or total_chars >= 240
        or max_len >= 90
        or (point_count >= 4 and total_chars >= 180)
    )
    very_dense = point_count >= 6 or total_chars >= 320 or max_len >= 110
    return {
        "points": points,
        "point_count": point_count,
        "total_chars": total_chars,
        "max_len": max_len,
        "short_points": short_points,
        "dense": dense,
        "very_dense": very_dense,
    }


def _should_split_slide(slide: dict, density: dict) -> tuple[bool, str]:
    if _normalize_role(slide) != "content":
        return False, ""
    if slide.get("split_origin") or slide.get("role") == "chapter":
        return False, ""

    kind = slide.get("content_kind") or infer_content_kind(slide)
    image_mode = _normalize_image_mode(slide.get("image_mode"))
    if density["very_dense"]:
        return True, "텍스트가 많아 한 장에 담기 어렵습니다."
    if density["dense"] and density["point_count"] >= 5:
        return True, "포인트 수가 많아 두 장으로 나누는 편이 읽기 쉽습니다."
    if image_mode == "hero" and density["point_count"] >= 4:
        return True, "이미지를 크게 보여주려면 내용을 나누는 편이 좋습니다."
    if image_mode == "hero" and density["total_chars"] >= 160:
        return True, "이미지와 본문을 함께 크게 보여주기 위해 내용을 나누는 편이 좋습니다."
    if kind == "process" and density["point_count"] >= 5:
        return True, "단계형 설명이 길어져 두 장으로 나누는 편이 좋습니다."
    if kind == "compare" and (density["total_chars"] >= 160 or density["point_count"] >= 4):
        return True, "비교 항목이 많아 두 장으로 나누는 편이 좋습니다."
    if density["point_count"] >= 4 and density["max_len"] >= 78:
        return True, "긴 문장이 많아 두 장으로 나누는 편이 읽기 쉽습니다."
    return False, ""


def _build_compare_payload(slide: dict):
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
    slide["compare_left_title"] = left_title
    slide["compare_right_title"] = right_title
    slide["compare_left_points"] = left_points[:3]
    slide["compare_right_points"] = right_points[:3]


def _build_process_payload(slide: dict):
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    cleaned = [STEP_PREFIX_RE.sub("", point).strip() for point in points]
    slide["diagram_steps"] = [step for step in cleaned if step][:4]


def _ensure_notes(slide: dict) -> str:
    notes = _clean_text(slide.get("notes"))
    if notes:
        return notes

    role = _normalize_role(slide)
    title = _clean_text(slide.get("title")) or "이 슬라이드"
    points = [_clean_text(point) for point in slide.get("points", []) if _clean_text(point)]
    if role == "chapter":
        return f"{title} 파트로 넘어갑니다. 이번 섹션의 핵심 학습 목표를 짧게 안내합니다."
    if points:
        return f"{title}에서는 {points[0]}을 중심으로 설명하고, 이어서 핵심 포인트를 연결합니다."
    return f"{title}의 핵심 메시지를 짧고 분명하게 전달합니다."


def _build_chapter_slide(section_title: str, source_pages: str, anchor_slide: dict) -> dict:
    preview_point = _clean_text(anchor_slide.get("subtitle"))
    if not preview_point:
        points = [_clean_text(point) for point in anchor_slide.get("points", []) if _clean_text(point)]
        preview_point = points[0] if points else ""

    chapter_slide = {
        "type": "content",
        "role": "chapter",
        "title": section_title,
        "subtitle": preview_point,
        "points": [preview_point] if preview_point else [],
        "layout": "chapter",
        "content_kind": "chapter",
        "section_title": section_title,
        "source_pages": source_pages,
        "image_mode": "none",
        "image_relevance": "none",
        "notes": "",
        "chapter_origin": anchor_slide.get("title") or section_title,
    }
    chapter_slide["notes"] = _ensure_notes(chapter_slide)
    return chapter_slide


def _split_content_slide(slide: dict, density: dict) -> list[dict]:
    points = list(slide.get("points", []) or [])
    if len(points) <= 3:
        return [slide]

    chunk_size = 3 if density["very_dense"] or _normalize_image_mode(slide.get("image_mode")) == "hero" else 4
    chunks = [points[i:i + chunk_size] for i in range(0, len(points), chunk_size)]
    if len(chunks) <= 1:
        return [slide]

    split_origin = slide.get("split_origin") or _safe_hash(f"{slide.get('title')}|{slide.get('source_pages')}")
    results = []
    for index, chunk in enumerate(chunks, start=1):
        clone = deepcopy(slide)
        clone["points"] = chunk
        clone["split_origin"] = split_origin
        clone["split_part"] = index
        clone["split_total"] = len(chunks)
        clone["needs_split"] = False
        clone["split_reason"] = ""
        if index > 1:
            subtitle = _clean_text(clone.get("subtitle"))
            suffix = f"계속 {index}/{len(chunks)}"
            clone["subtitle"] = f"{subtitle} · {suffix}" if subtitle else suffix
        results.append(clone)
    return results


def _layout_from_signal(slide: dict) -> str:
    role = _normalize_role(slide)
    if role == "chapter":
        return "chapter"

    existing = _normalize_layout(slide.get("layout"))
    density = _measure_density(slide)
    kind = slide.get("content_kind") or infer_content_kind(slide)
    image_mode = _normalize_image_mode(slide.get("image_mode"))
    orientation = _clean_text(slide.get("image_orientation")).lower() or "square"
    has_image = bool(slide.get("image_asset_name"))

    if existing not in {"auto", ""}:
        layout = existing
    elif kind == "process":
        if image_mode == "hero" and has_image and density["point_count"] <= 4:
            layout = "image_left" if orientation == "portrait" else "image_top"
        else:
            layout = "process"
    elif kind == "compare":
        if image_mode == "hero" and has_image:
            layout = "image_left" if orientation == "portrait" else "image_top"
        else:
            layout = "compare"
    elif image_mode == "hero" and has_image:
        layout = "image_left" if orientation == "portrait" else "image_top"
    elif kind == "case":
        layout = "split"
    elif kind == "data":
        layout = "card" if density["short_points"] >= min(density["point_count"], 4) else "highlight"
    elif density["point_count"] <= 2:
        layout = "highlight"
    elif _clean_text(slide.get("subtitle")) and density["point_count"] <= 4:
        layout = "split"
    elif density["point_count"] >= 4 and density["short_points"] >= min(density["point_count"], 4):
        layout = "card"
    else:
        layout = "classic"

    return _apply_layout_safety(layout, slide, density)


def _apply_layout_safety(layout: str, slide: dict, density: dict) -> str:
    role = _normalize_role(slide)
    if role == "chapter":
        return "chapter"

    image_mode = _normalize_image_mode(slide.get("image_mode"))
    has_image = bool(slide.get("image_asset_name"))
    orientation = _clean_text(slide.get("image_orientation")).lower() or "square"
    image_relevance = _clean_text(slide.get("image_relevance")).lower()

    if layout == "compare" and has_image and image_mode == "hero":
        return "image_left" if orientation == "portrait" else "image_top"
    if layout == "compare" and has_image and image_mode == "support":
        return "classic"
    if layout == "process" and has_image and image_mode == "hero" and density["point_count"] >= 4:
        return "image_left" if orientation == "portrait" else "image_top"
    if layout == "process" and has_image and image_mode == "support":
        return "classic"
    if layout == "highlight" and has_image and image_mode == "hero" and density["point_count"] >= 3:
        return "image_left" if orientation == "portrait" else "image_top"
    if layout == "highlight" and has_image and image_mode == "support":
        return "classic"
    if layout == "card" and has_image:
        return "classic"
    if layout in {"image_left", "image_top"} and not has_image:
        return "classic"
    if layout in {"card", "compare", "process"} and density["very_dense"]:
        return "classic"
    if has_image and image_relevance in {"low", "none"} and layout in {"compare", "process", "card"}:
        return "classic"
    if image_mode == "hero" and not has_image:
        return "classic"
    return layout


def _decision_note_for_slide(slide: dict) -> str:
    role = _normalize_role(slide)
    if role == "chapter":
        section = _clean_text(slide.get("section_title") or slide.get("title"))
        return f"{section or '새 섹션'}으로 넘어가는 챕터 슬라이드입니다."

    parts = []
    kind = _clean_text(slide.get("content_kind"))
    source_pages = _clean_text(slide.get("source_pages"))
    layout = _normalize_layout(slide.get("layout"))
    image_mode = _normalize_image_mode(slide.get("image_mode"))
    image_relevance = _clean_text(slide.get("image_relevance")).lower() or "none"
    image_choice_mode = _normalize_image_choice_mode(slide.get("image_choice_mode"))

    if source_pages:
        parts.append(f"근거 페이지 {source_pages}")
    if kind == "compare":
        parts.append("비교 설명에 맞춰 정리했습니다")
    elif kind == "process":
        parts.append("단계 흐름이 잘 보이도록 구성했습니다")
    elif kind == "data":
        parts.append("짧은 정보 조각이 한눈에 보이도록 구성했습니다")
    elif kind == "case":
        parts.append("사례 설명이 자연스럽게 이어지도록 구성했습니다")
    else:
        parts.append("일반 설명형 흐름으로 정리했습니다")

    if image_choice_mode == "manual_none":
        parts.append("이미지는 제외하고 텍스트 중심으로 유지합니다")
    elif slide.get("image_asset_name"):
        if image_choice_mode == "manual":
            parts.append("사용자가 PDF 이미지를 직접 선택했습니다")
        elif image_mode == "hero":
            parts.append("PDF 이미지를 크게 보여주는 레이아웃을 선택했습니다")
        elif image_mode == "support":
            parts.append("본문 이해를 돕는 보조 이미지로 연결했습니다")
        if image_relevance not in {"none", "manual"}:
            parts.append(f"이미지 관련성 {image_relevance}")

    if slide.get("split_origin"):
        parts.append("내용 과밀로 분할된 슬라이드입니다")
    elif slide.get("needs_split"):
        parts.append(_clean_text(slide.get("split_reason")))

    if layout in {"image_left", "image_top"}:
        parts.append("이미지가 본문보다 더 잘 보이도록 비중을 높였습니다")

    return " · ".join(part for part in parts if part)


def _normalize_content_slide(slide: dict, content_index: int, total_content: int, selected_pages: list[int] | None):
    slide["type"] = slide.get("type", "content") or "content"
    slide["role"] = _normalize_role(slide)
    slide["title"] = _clean_text(slide.get("title")) or f"핵심 내용 {content_index}"
    slide["subtitle"] = _clean_text(slide.get("subtitle"))
    slide["source_pages"] = _normalize_source_pages(slide.get("source_pages"), selected_pages)
    if not slide["source_pages"]:
        slide["source_pages"] = _fallback_source_pages(content_index - 1, total_content, selected_pages)
    slide["section_title"] = _infer_section_title(slide)
    slide["image_mode"] = _normalize_image_mode(slide.get("image_mode"))
    slide["image_relevance"] = _clean_text(slide.get("image_relevance")).lower() or "none"
    slide["image_orientation"] = _clean_text(slide.get("image_orientation")).lower() or ""
    slide["image_choice_mode"] = _normalize_image_choice_mode(slide.get("image_choice_mode"))
    slide["variant_origin"] = _clean_text(slide.get("variant_origin"))

    if slide["role"] == "chapter":
        chapter_points = _dedupe_points(list(slide.get("points", [])), limit=1)
        if not chapter_points and slide["subtitle"]:
            chapter_points = [slide["subtitle"]]
        slide["points"] = chapter_points
        slide["content_kind"] = "chapter"
        slide["layout"] = "chapter"
        slide["notes"] = _ensure_notes(slide)
        slide["needs_split"] = False
        slide["split_reason"] = ""
        slide["decision_note"] = _decision_note_for_slide(slide)
        return slide

    slide["points"] = _dedupe_points(list(slide.get("points", [])), limit=6)
    slide["content_kind"] = infer_content_kind(slide)
    density = _measure_density(slide)
    slide["needs_split"], slide["split_reason"] = _should_split_slide(slide, density)
    slide["layout"] = _layout_from_signal(slide)
    slide["notes"] = _ensure_notes(slide)

    if slide["content_kind"] == "process":
        _build_process_payload(slide)
    elif slide["content_kind"] == "compare":
        _build_compare_payload(slide)

    slide["decision_note"] = _decision_note_for_slide(slide)

    return slide


def _normalize_non_content_slide(slide: dict):
    slide_type = slide.get("type", "content")
    slide["type"] = slide_type
    slide["role"] = _normalize_role(slide)
    slide["variant_origin"] = _clean_text(slide.get("variant_origin"))
    slide["decision_note"] = _clean_text(slide.get("decision_note"))

    if slide_type == "agenda":
        slide["items"] = _dedupe_points(list(slide.get("items", [])), limit=8)
        slide["title"] = _clean_text(slide.get("title")) or "목차"
        slide["decision_note"] = slide["decision_note"] or "강의 전체 흐름을 먼저 파악하도록 목차를 정리했습니다."
        return slide

    if slide_type == "summary":
        slide["points"] = _dedupe_points(list(slide.get("points", [])), limit=6)
        slide["title"] = _clean_text(slide.get("title")) or "핵심 요약"
        slide["notes"] = _ensure_notes(slide)
        slide["decision_note"] = slide["decision_note"] or "수업 마지막에 핵심 개념을 다시 확인하는 요약 슬라이드입니다."
        return slide

    slide["title"] = _clean_text(slide.get("title")) or "강의 교안"
    slide["subtitle"] = _clean_text(slide.get("subtitle"))
    slide["notes"] = _ensure_notes(slide)
    slide["decision_note"] = slide["decision_note"] or "강의 시작을 안내하는 표지 슬라이드입니다."
    return slide


def _expand_slides(slides: list[dict]) -> list[dict]:
    expanded = []
    current_section = ""

    for slide in slides:
        role = _normalize_role(slide)
        if role == "chapter":
            expanded.append(slide)
            current_section = _clean_text(slide.get("section_title") or slide.get("title"))
            continue

        if role == "content":
            section_title = _clean_text(slide.get("section_title"))
            prev_slide = expanded[-1] if expanded else None
            prev_is_same_chapter = (
                prev_slide
                and _normalize_role(prev_slide) == "chapter"
                and _clean_text(prev_slide.get("section_title") or prev_slide.get("title")) == section_title
            )
            if section_title and section_title != current_section and not prev_is_same_chapter:
                expanded.append(_build_chapter_slide(section_title, slide.get("source_pages", ""), slide))
                current_section = section_title

            density = _measure_density(slide)
            if slide.get("needs_split") and not slide.get("split_origin"):
                expanded.extend(_split_content_slide(slide, density))
            else:
                expanded.append(slide)
            continue

        expanded.append(slide)

    return expanded


def build_outline(slides: list[dict]) -> list[dict]:
    outline = []
    for index, slide in enumerate(slides, start=1):
        role = _normalize_role(slide)
        outline.append(
            {
                "index": index,
                "type": slide.get("type", "content"),
                "role": role,
                "title": slide.get("title", ""),
                "subtitle": slide.get("subtitle", ""),
                "layout": slide.get("layout", ""),
                "content_kind": slide.get("content_kind", ""),
                "source_pages": slide.get("source_pages", ""),
                "point_count": len(slide.get("points", []) or slide.get("items", []) or []),
                "has_image": bool(slide.get("image_asset_name")),
                "image_page": slide.get("image_page"),
                "image_mode": slide.get("image_mode", "none"),
                "image_relevance": slide.get("image_relevance", "none"),
                "image_choice_mode": slide.get("image_choice_mode", "auto"),
                "needs_split": bool(slide.get("needs_split")),
                "section_title": slide.get("section_title", ""),
                "decision_note": slide.get("decision_note", ""),
            }
        )
    return outline


def build_quality_summary(slides: list[dict]) -> dict:
    warnings = []
    content_slides = [
        slide for slide in slides
        if slide.get("type", "content") == "content" and _normalize_role(slide) == "content"
    ]
    chapter_slides = [slide for slide in slides if _normalize_role(slide) == "chapter"]
    missing_sources = sum(1 for slide in content_slides if not slide.get("source_pages"))
    missing_images = sum(1 for slide in content_slides if not slide.get("image_asset_name"))
    low_relevance_images = sum(1 for slide in content_slides if _clean_text(slide.get("image_relevance")).lower() == "low")
    hero_images = sum(1 for slide in content_slides if _normalize_image_mode(slide.get("image_mode")) == "hero")
    process_count = sum(1 for slide in content_slides if slide.get("content_kind") == "process")
    compare_count = sum(1 for slide in content_slides if slide.get("content_kind") == "compare")
    dense_slides = 0
    notes_missing = 0
    duplicate_titles = 0
    split_slides = 0
    seen_titles = {}
    kind_counts = {"process": 0, "compare": 0, "case": 0, "data": 0, "explain": 0, "chapter": len(chapter_slides)}

    for slide in content_slides:
        title_key = _clean_text(slide.get("title")).lower()
        if title_key:
            seen_titles[title_key] = seen_titles.get(title_key, 0) + 1

        density = _measure_density(slide)
        if density["dense"]:
            dense_slides += 1
        if not _clean_text(slide.get("notes")):
            notes_missing += 1
        if slide.get("split_origin"):
            split_slides += 1

        kind = slide.get("content_kind") or "explain"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    duplicate_titles = sum(count - 1 for count in seen_titles.values() if count > 1)

    if chapter_slides:
        warnings.append(f"챕터 분리 슬라이드 {len(chapter_slides)}장")
    if missing_sources:
        warnings.append(f"근거 페이지가 비어 있는 내용 슬라이드 {missing_sources}장")
    if missing_images:
        warnings.append(f"PDF 이미지가 직접 연결되지 않은 내용 슬라이드 {missing_images}장")
    if low_relevance_images:
        warnings.append(f"연결된 이미지 relevance가 낮은 슬라이드 {low_relevance_images}장")
    if dense_slides:
        warnings.append(f"텍스트 밀도가 높은 내용 슬라이드 {dense_slides}장")
    if duplicate_titles:
        warnings.append(f"제목이 겹치는 슬라이드 {duplicate_titles}장")
    if notes_missing:
        warnings.append(f"발표자 노트가 비어 있는 내용 슬라이드 {notes_missing}장")

    return {
        "content_count": len(content_slides),
        "chapter_count": len(chapter_slides),
        "hero_image_count": hero_images,
        "split_slide_count": split_slides,
        "process_count": process_count,
        "compare_count": compare_count,
        "missing_sources": missing_sources,
        "missing_images": missing_images,
        "low_relevance_images": low_relevance_images,
        "dense_slides": dense_slides,
        "duplicate_titles": duplicate_titles,
        "notes_missing": notes_missing,
        "kind_counts": kind_counts,
        "warnings": warnings,
    }


def review_slides(slides_data: list[dict], selected_pages: list[int] | None = None) -> dict:
    raw_slides = deepcopy(slides_data or [])
    normalized = []
    content_total = sum(1 for slide in raw_slides if str(slide.get("type", "content")) == "content")
    content_index = 0

    for slide in raw_slides:
        slide_type = str(slide.get("type", "content") or "content").strip().lower()
        if slide_type != "content":
            normalized.append(_normalize_non_content_slide(slide))
            continue

        content_index += 1
        normalized.append(_normalize_content_slide(slide, content_index, content_total, selected_pages))

    expanded = _expand_slides(normalized)

    final_slides = []
    content_total = sum(1 for slide in expanded if str(slide.get("type", "content")) == "content" and _normalize_role(slide) == "content")
    content_index = 0
    for slide in expanded:
        if str(slide.get("type", "content")) != "content":
            final_slides.append(_normalize_non_content_slide(slide))
            continue

        if _normalize_role(slide) == "content":
            content_index += 1
        final_slides.append(_normalize_content_slide(slide, max(content_index, 1), max(content_total, 1), selected_pages))

    return {
        "slides": final_slides,
        "outline": build_outline(final_slides),
        "quality": build_quality_summary(final_slides),
    }
