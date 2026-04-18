from __future__ import annotations

import json
import os
import re
from collections import Counter
from copy import deepcopy

from core.claude_analyzer import analyze_pdf
from core.pdf_parser import extract_pdf_images, parse_page_range
from core.slide_enricher import attach_pdf_images_to_slides
from core.slide_quality import build_outline, build_quality_summary, review_slides


def _curriculum_from_slides(slides: list[dict]) -> dict:
    content_slides = [slide for slide in slides if str(slide.get("type")) == "content"]
    objectives = []
    concepts = []
    structure = []
    seen_sections = set()
    for index, slide in enumerate(content_slides, start=1):
        title = str(slide.get("title") or "").strip()
        subtitle = str(slide.get("subtitle") or "").strip()
        section = str(slide.get("section_title") or title).strip()
        points = [str(point).strip() for point in slide.get("points", []) if str(point).strip()]
        if section and section not in seen_sections:
            seen_sections.add(section)
            structure.append({
                "slide_no": index,
                "type": slide.get("role") or "content",
                "section_title": section,
                "title": title,
                "subtitle": subtitle,
                "source_pages": slide.get("source_pages", ""),
                "image_candidate": bool(slide.get("image_asset_name") or slide.get("image_mode") == "hero"),
                "content_kind": slide.get("content_kind", "explain"),
            })
        if title and len(objectives) < 5:
            objectives.append(title)
        concepts.extend(points[:2])
    deduped_concepts = []
    seen = set()
    for concept in concepts:
        key = concept.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped_concepts.append(concept)
        if len(deduped_concepts) >= 8:
            break
    return {
        "learning_objectives": objectives[:5],
        "structure": structure[: max(len(structure), 1)],
        "key_concepts": deduped_concepts,
        "difficulty_level": "중급",
    }


def design_curriculum_fallback(page_plan: dict, page_preview: dict, slide_count: int | None, lecture_goal: str) -> dict:
    headings = page_preview.get("headings", []) or []
    objective_seed = [item.get("heading", "") for item in headings if item.get("heading")]
    objectives = objective_seed[:5] or ["핵심 개념 이해", "강의 흐름 파악", "핵심 용어 정리"]
    structure = []
    for index, item in enumerate(headings, start=1):
        structure.append(
            {
                "slide_no": index,
                "type": "content",
                "section_title": item.get("heading", f"섹션 {index}"),
                "title": item.get("heading", f"섹션 {index}"),
                "subtitle": "",
                "source_pages": str(item.get("page", "")),
                "image_candidate": True,
                "content_kind": "explain",
            }
        )
    return {
        "learning_objectives": objectives,
        "structure": structure,
        "key_concepts": objectives[:8],
        "difficulty_level": "중급" if lecture_goal != "intro" else "초급",
        "page_summary": page_preview.get("page_summary", ""),
        "selection_note": page_plan.get("selection_note", ""),
    }


def write_slides_from_pdf(
    pdf_path: str,
    slide_count: int | None,
    page_range: str | None,
    extra_prompt: str | None,
    lecture_goal: str | None,
    page_plan: dict,
    curriculum: dict | None = None,
    revision_request: str | None = None,
) -> list[dict]:
    guidance = []
    if extra_prompt:
        guidance.append(str(extra_prompt).strip())
    if curriculum:
        objectives = curriculum.get("learning_objectives") or []
        sections = curriculum.get("structure") or []
        if objectives:
            guidance.append("학습목표: " + " / ".join(str(item) for item in objectives[:5]))
        if sections:
            section_names = [str(item.get("section_title") or item.get("title") or "").strip() for item in sections]
            section_names = [name for name in section_names if name]
            if section_names:
                guidance.append("강의 흐름: " + " -> ".join(section_names[:10]))
    if revision_request:
        guidance.append("수정 지시: " + revision_request.strip())

    slides = analyze_pdf(
        pdf_path,
        slide_count=slide_count,
        page_range=page_range,
        extra_prompt="\n".join(part for part in guidance if part),
        page_plan=page_plan,
        lecture_goal=lecture_goal,
    )
    return slides


def fact_check_fallback(slides: list[dict], curriculum: dict, source_excerpt: str) -> dict:
    issues = []
    content_slides = [slide for slide in slides if str(slide.get("type", "content")) == "content"]
    if not content_slides:
        issues.append("내용 슬라이드가 생성되지 않았습니다.")
    for slide in content_slides:
        if not slide.get("source_pages"):
            issues.append(f"근거 페이지가 비어 있는 슬라이드: {slide.get('title', '제목 없음')}")
        if not slide.get("points") and (slide.get("role") != "chapter"):
            issues.append(f"포인트가 비어 있는 슬라이드: {slide.get('title', '제목 없음')}")
    objective_titles = [str(item).strip() for item in curriculum.get("learning_objectives", []) if str(item).strip()]
    if objective_titles and not any(obj[:4] in source_excerpt for obj in objective_titles):
        issues.append("학습목표와 원문 발췌의 직접 연결성이 약합니다.")
    status = "PASS" if not issues else ("REJECT" if len(issues) >= 6 else "REVISE")
    return {
        "status": status,
        "issues": issues,
        "revision_request": " / ".join(issues[:4]) if issues else "",
    }


def _difficulty_cycle(counts: dict[str, int]) -> list[str]:
    items = []
    for key in ["하", "중", "상"]:
        items.extend([key] * max(0, counts.get(key, 0)))
    return items or ["중"]


def generate_exam_fallback(
    slides: list[dict],
    question_count: int,
    difficulty_counts: dict[str, int],
) -> dict:
    content_slides = [slide for slide in slides if slide.get("type") == "content" and slide.get("role") != "chapter"]
    if not content_slides:
        return {"exam_title": "자동 생성 시험지", "questions": []}

    difficulty_cycle = _difficulty_cycle(difficulty_counts)
    questions = []
    for index in range(question_count):
        slide = content_slides[index % len(content_slides)]
        points = [str(point).strip() for point in slide.get("points", []) if str(point).strip()]
        key_point = points[index % len(points)] if points else str(slide.get("subtitle") or slide.get("title") or "").strip()
        difficulty = difficulty_cycle[index % len(difficulty_cycle)]
        q_type = (
            "multiple_choice_single" if index % 4 == 0 else
            "multiple_choice_multi" if index % 4 == 1 else
            "subjective_short" if index % 4 == 2 else
            "subjective_long"
        )
        question = {
            "id": f"q{index + 1}",
            "type": q_type,
            "difficulty": difficulty,
            "points": 5 if difficulty == "하" else (7 if difficulty == "중" else 10),
            "prompt": f"{slide.get('title', '핵심 개념')}와 관련하여 '{key_point}'를 설명하거나 구분하세요.",
            "source_pages": slide.get("source_pages", ""),
            "explanation": f"{key_point}를 중심으로 원문 내용을 확인하도록 설계한 문항입니다.",
        }
        if q_type == "multiple_choice_single":
            question["choices"] = [
                key_point,
                "원문에 없는 선택지",
                "반대 개념",
                "무관한 보기",
            ]
            question["answer"] = "1"
        elif q_type == "multiple_choice_multi":
            question["choices"] = [
                key_point,
                str(slide.get("title", "핵심 개념")),
                "원문과 무관한 보기",
                "반대 진술",
            ]
            question["answer"] = ["1", "2"]
        else:
            question["choices"] = []
            question["answer"] = key_point
        questions.append(question)
    return {"exam_title": "자동 생성 시험지", "questions": questions}


def _dedupe_questions(questions: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for question in questions:
        prompt = str(question.get("prompt") or "").strip().lower()
        if not prompt or prompt in seen:
            continue
        seen.add(prompt)
        deduped.append(question)
    return deduped


def review_questions_fallback(questions: list[dict]) -> dict:
    issues = []
    reviewed = []
    for question in _dedupe_questions(questions):
        item = deepcopy(question)
        q_type = str(item.get("type") or "")
        if q_type == "multiple_choice_multi":
            answer = item.get("answer") or []
            if not isinstance(answer, list) or len(answer) < 2:
                item["answer"] = ["1", "2"]
                issues.append(f"다중선택 정답 수를 보정했습니다: {item.get('id')}")
        reviewed.append(item)
    status = "PASS" if not issues else "REVISE"
    return {
        "status": status,
        "issues": issues,
        "reviewed_questions": reviewed,
        "shuffle_ready": True,
    }


def _candidate_asset_pages(slides: list[dict], selected_pages: list[int] | None, radius: int = 1, max_pages: int = 72) -> list[int]:
    allowed = set(int(page) for page in (selected_pages or []) if int(page) >= 1)
    pages = set()
    for slide in slides or []:
        if str(slide.get("type", "content")) != "content":
            continue
        source_pages = parse_page_range(str(slide.get("source_pages", "")), max(allowed or {0}))
        for page in source_pages:
            for delta in range(-radius, radius + 1):
                candidate = page + delta
                if candidate < 1:
                    continue
                if allowed and candidate not in allowed:
                    continue
                pages.add(candidate)
    ordered = sorted(pages)
    return ordered[:max_pages]


def _asset_summary(assets: list[dict]) -> str:
    parts = []
    for asset in assets[:12]:
        parts.append(
            f"- {asset.get('asset_name')} / page {asset.get('page')} / "
            f"{asset.get('orientation')} / {asset.get('width')}x{asset.get('height')}"
        )
    return "\n".join(parts) or "추출 이미지 없음"


def _apply_layout_overrides(slides: list[dict], overrides: dict | None) -> list[dict]:
    if not isinstance(overrides, dict):
        return slides
    override_rows = overrides.get("slide_overrides") or []
    if not isinstance(override_rows, list):
        return slides
    updated = deepcopy(slides)
    for row in override_rows:
        try:
            index = int(row.get("slide_index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not (0 <= index < len(updated)):
            continue
        slide = updated[index]
        if str(slide.get("type")) != "content":
            continue
        layout = str(row.get("layout") or "").strip()
        image_mode = str(row.get("image_mode") or "").strip()
        note = str(row.get("note") or "").strip()
        if layout:
            slide["layout"] = layout
        if image_mode:
            slide["image_mode"] = image_mode
        if note:
            existing = str(slide.get("decision_note") or "").strip()
            slide["decision_note"] = f"{existing} · {note}" if existing else note
    return updated


def apply_layout_design(
    uid: str,
    pdf_path: str,
    slides: list[dict],
    page_plan: dict,
    asset_dir: str,
    layout_overrides: dict | None = None,
) -> dict:
    reviewed = review_slides(slides, selected_pages=page_plan.get("selected_pages"))
    asset_pages = _candidate_asset_pages(reviewed["slides"], page_plan.get("selected_pages"))
    assets = []
    if asset_pages:
        assets = extract_pdf_images(
            pdf_path,
            asset_pages,
            asset_dir,
            bundle_uid=uid,
            max_total=max(36, min(len(reviewed["slides"]) * 3, 96)),
            max_per_page=3,
        )
    prepared = attach_pdf_images_to_slides(reviewed["slides"], assets)
    prepared = _apply_layout_overrides(prepared, layout_overrides)
    final_review = review_slides(prepared, selected_pages=page_plan.get("selected_pages"))
    final_slides = attach_pdf_images_to_slides(final_review["slides"], assets)
    final_review = review_slides(final_slides, selected_pages=page_plan.get("selected_pages"))
    return {
        "slides": final_review["slides"],
        "outline": build_outline(final_review["slides"]),
        "quality": build_quality_summary(final_review["slides"]),
        "assets": assets,
        "asset_summary": _asset_summary(assets),
    }


def build_exam_summary(questions: list[dict]) -> dict:
    counts = Counter(str(item.get("difficulty") or "중") for item in questions or [])
    type_counts = Counter(str(item.get("type") or "") for item in questions or [])
    return {
        "count": len(questions or []),
        "difficulty_counts": dict(counts),
        "type_counts": dict(type_counts),
    }
