from __future__ import annotations


def build_pm_review_task(curriculum_json: str, slides_json: str, questions_json: str | None = None) -> str:
    parts = [
        "전체 강의안/문제지 초안을 최종 검토하세요.",
        f"커리큘럼:\n{curriculum_json}",
        f"슬라이드:\n{slides_json}",
    ]
    if questions_json:
        parts.append(f"문항:\n{questions_json}")
    parts.append("출력은 summary, risks, status를 포함한 JSON 객체여야 합니다.")
    return "\n\n".join(parts)
