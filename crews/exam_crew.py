from __future__ import annotations

from agents import build_question_designer, build_reviewer
from crews.common import run_single_agent_json
from tasks import build_question_task, build_review_task


def run_question_designer_stage(curriculum_json: str, slides_json: str, question_count: int, difficulty_text: str, source_excerpt: str):
    agent = build_question_designer()
    return run_single_agent_json(
        agent,
        build_question_task(curriculum_json, slides_json, question_count, difficulty_text, source_excerpt),
        "Questions JSON object",
    )


def run_reviewer_stage(questions_json: str, slides_json: str):
    agent = build_reviewer()
    return run_single_agent_json(
        agent,
        build_review_task(questions_json, slides_json),
        "Review JSON object",
    )
