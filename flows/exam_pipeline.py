from __future__ import annotations

import json

from tools.slide_tool import generate_exam_fallback, review_questions_fallback


def _difficulty_counts(exam_settings: dict) -> dict[str, int]:
    return {
        "하": max(0, int(exam_settings.get("difficulty_easy", 20) or 0)),
        "중": max(0, int(exam_settings.get("difficulty_medium", 60) or 0)),
        "상": max(0, int(exam_settings.get("difficulty_hard", 20) or 0)),
    }


def _difficulty_text(exam_settings: dict) -> str:
    counts = _difficulty_counts(exam_settings)
    return f"하 {counts['하']} / 중 {counts['중']} / 상 {counts['상']}"


def run_question_stage(
    curriculum: dict,
    slides: list[dict],
    question_count: int,
    exam_settings: dict,
    source_excerpt: str,
):
    difficulty_text = _difficulty_text(exam_settings)
    try:
        from crews.exam_crew import run_question_designer_stage

        result = run_question_designer_stage(
            json.dumps(curriculum, ensure_ascii=False),
            json.dumps(slides or [], ensure_ascii=False),
            question_count,
            difficulty_text,
            source_excerpt,
        )
        if isinstance(result, dict) and isinstance(result.get("questions"), list):
            return result, True, "CrewAI question designer completed"
    except Exception:
        pass

    fallback = generate_exam_fallback(slides, question_count, _difficulty_counts(exam_settings))
    return fallback, False, "Fallback question generation completed"


def run_review_stage(questions: list[dict], slides: list[dict]):
    try:
        from crews.exam_crew import run_reviewer_stage

        result = run_reviewer_stage(
            json.dumps(questions or [], ensure_ascii=False),
            json.dumps(slides or [], ensure_ascii=False),
        )
        if isinstance(result, dict) and result.get("status"):
            return result, True, "CrewAI reviewer completed"
    except Exception:
        pass

    fallback = review_questions_fallback(questions)
    return fallback, False, "Fallback reviewer heuristic completed"
