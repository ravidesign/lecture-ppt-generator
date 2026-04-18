from __future__ import annotations

from agents import build_orchestrator
from crews.common import run_single_agent_json
from tasks import build_pm_review_task


def run_pm_review_stage(curriculum_json: str, slides_json: str, questions_json: str | None = None):
    agent = build_orchestrator()
    return run_single_agent_json(
        agent,
        build_pm_review_task(curriculum_json, slides_json, questions_json),
        "PM summary JSON object",
    )
