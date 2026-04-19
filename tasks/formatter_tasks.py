from __future__ import annotations


def build_formatter_task(slides_json: str, questions_json: str, exam_settings_json: str) -> str:
    return (
        "다음 draft를 바탕으로 최종 산출물 생성 체크리스트를 검토하세요.\n\n"
        f"슬라이드 JSON:\n{slides_json}\n\n"
        f"문항 JSON:\n{questions_json}\n\n"
        f"시험 설정 JSON:\n{exam_settings_json}\n\n"
        "출력은 JSON 객체여야 하며 format_status, artifact_plan, notes를 포함해야 합니다. "
        "artifact_plan에는 ppt, exam, answer, exam_a, exam_b 중 필요한 산출물을 배열로 명시하세요."
    )
