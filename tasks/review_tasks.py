from __future__ import annotations


def build_review_task(questions_json: str, slides_json: str) -> str:
    return (
        "문항 세트를 검토하고 중복 제거, 난이도 점검, 다중선택 정답 수 검증을 수행하세요.\n"
        f"문항 JSON:\n{questions_json}\n\n"
        f"슬라이드 JSON:\n{slides_json}\n"
        "출력은 status, issues, reviewed_questions, shuffle_ready를 포함한 JSON 객체여야 합니다."
    )
