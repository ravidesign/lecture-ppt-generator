from __future__ import annotations

from agents import (
    build_content_writer,
    build_curriculum_designer,
    build_fact_checker,
    build_layout_designer,
)
from crews.common import run_single_agent_json
from tasks import (
    build_content_task,
    build_curriculum_task,
    build_factcheck_task,
    build_layout_task,
)


def run_curriculum_designer_stage(page_summary: str, heading_lines: str, slide_instruction: str, lecture_goal: str):
    agent = build_curriculum_designer()
    return run_single_agent_json(
        agent,
        build_curriculum_task(page_summary, heading_lines, slide_instruction, lecture_goal),
        "Curriculum JSON object",
    )


def run_content_writer_stage(curriculum_json: str, revision_request: str | None = None):
    agent = build_content_writer()
    return run_single_agent_json(
        agent,
        build_content_task(curriculum_json, revision_request=revision_request),
        "Slide JSON array",
    )


def run_fact_checker_stage(curriculum_json: str, slides_json: str, source_excerpt: str):
    agent = build_fact_checker()
    return run_single_agent_json(
        agent,
        build_factcheck_task(curriculum_json, slides_json, source_excerpt),
        "Fact check JSON object",
    )


def run_layout_designer_stage(slides_json: str, asset_summary: str):
    agent = build_layout_designer()
    return run_single_agent_json(
        agent,
        build_layout_task(slides_json, asset_summary),
        "Layout override JSON object",
    )
