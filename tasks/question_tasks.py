from __future__ import annotations


def build_question_task(curriculum_json: str, slides_json: str, question_count: int, difficulty_text: str, source_excerpt: str) -> str:
    return (
        "강의 내용만을 근거로 시험 문제를 작성하세요.\n"
        f"- 목표 문항 수: {question_count}\n"
        f"- 난이도 비율: {difficulty_text}\n"
        "문항 유형은 주관식 단답형, 주관식 서술형, 객관식 단일선택, 객관식 다중선택을 포함하세요.\n"
        f"커리큘럼:\n{curriculum_json}\n\n"
        f"슬라이드 초안:\n{slides_json}\n\n"
        f"원문 발췌:\n{source_excerpt}\n"
        "출력은 questions 배열 JSON 객체여야 하며, 각 문제는 정답/해설/난이도/출처 페이지를 포함해야 합니다."
    )
