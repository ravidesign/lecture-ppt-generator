from __future__ import annotations


def build_curriculum_task(page_summary: str, heading_lines: str, slide_instruction: str, lecture_goal: str) -> str:
    return (
        "선택된 PDF 범위를 바탕으로 강의 구조를 설계하세요.\n"
        f"- 사용 범위: {page_summary or '전체'}\n"
        f"- 강의 목표 유형: {lecture_goal}\n"
        f"- 슬라이드 요구: {slide_instruction}\n"
        f"- 미리 파악한 표제 목록:\n{heading_lines}\n"
        "학습목표 3~5개, 핵심 개념, 섹션 구조, 이미지 활용 가능 섹션을 JSON으로 정리하세요."
    )
