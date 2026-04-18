from __future__ import annotations

import json
from copy import deepcopy

from tools.pdf_tool import build_page_source_excerpt, build_page_summary, build_preview_headings
from tools.slide_tool import (
    apply_layout_design,
    design_curriculum_fallback,
    fact_check_fallback,
    write_slides_from_pdf,
)


def run_curriculum_stage(
    pdf_path: str,
    page_plan: dict,
    page_plan_preview: dict,
    slide_count: int | None,
    lecture_goal: str,
):
    page_summary = build_page_summary(page_plan.get("selected_pages", []))
    headings = build_preview_headings(pdf_path, page_plan)
    heading_lines = "\n".join(
        f"- {row.get('page', '')}p · {row.get('heading', '')}".strip()
        for row in headings
        if row.get("heading")
    )
    slide_instruction = (
        "챕터 전환은 chapter 슬라이드로 분리하고, 과밀한 content 슬라이드는 자동 분할하세요. "
        "이미지가 있는 슬라이드는 image_mode를 함께 판단하세요."
    )

    try:
        from crews.lecture_crew import run_curriculum_designer_stage

        result = run_curriculum_designer_stage(
            page_summary,
            heading_lines or "(대표 heading 없음)",
            slide_instruction,
            lecture_goal,
        )
        if isinstance(result, dict):
            return result, True, "CrewAI curriculum stage completed"
    except Exception:
        pass

    fallback = design_curriculum_fallback(page_plan, page_plan_preview, slide_count, lecture_goal)
    return fallback, False, "Fallback curriculum generated from selected headings"


def run_content_stage(
    pdf_path: str,
    slide_count: int | None,
    page_range: str | None,
    extra_prompt: str | None,
    lecture_goal: str,
    page_plan: dict,
    curriculum: dict,
    revision_request: str | None = None,
):
    slides = write_slides_from_pdf(
        pdf_path=pdf_path,
        slide_count=slide_count,
        page_range=page_range,
        extra_prompt=extra_prompt,
        lecture_goal=lecture_goal,
        page_plan=page_plan,
        curriculum=curriculum,
        revision_request=revision_request,
    )
    return slides


def run_fact_check_stage(curriculum: dict, slides: list[dict], source_excerpt: str):
    slides_json = json.dumps(slides, ensure_ascii=False)
    curriculum_json = json.dumps(curriculum, ensure_ascii=False)
    try:
        from crews.lecture_crew import run_fact_checker_stage

        result = run_fact_checker_stage(curriculum_json, slides_json, source_excerpt)
        if isinstance(result, dict) and result.get("status"):
            return result, True, "CrewAI fact checker completed"
    except Exception:
        pass

    fallback = fact_check_fallback(slides, curriculum, source_excerpt)
    return fallback, False, "Fallback fact-check heuristic completed"


def run_layout_stage(
    uid: str,
    pdf_path: str,
    slides: list[dict],
    page_plan: dict,
    asset_dir: str,
):
    layout_overrides = None
    try:
        from crews.lecture_crew import run_layout_designer_stage
        from tools.slide_tool import _asset_summary  # type: ignore[attr-defined]

        layout_seed = apply_layout_design(
            uid=uid,
            pdf_path=pdf_path,
            slides=slides,
            page_plan=page_plan,
            asset_dir=asset_dir,
            layout_overrides=None,
        )
        layout_overrides = run_layout_designer_stage(
            json.dumps(layout_seed["slides"], ensure_ascii=False),
            _asset_summary(layout_seed["assets"]),
        )
    except Exception:
        layout_overrides = None

    return apply_layout_design(
        uid=uid,
        pdf_path=pdf_path,
        slides=deepcopy(slides),
        page_plan=page_plan,
        asset_dir=asset_dir,
        layout_overrides=layout_overrides,
    )
