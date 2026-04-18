from __future__ import annotations


def build_content_task(curriculum_json: str, revision_request: str | None = None) -> str:
    revise_text = f"\n수정 지시:\n{revision_request}\n" if revision_request else ""
    return (
        "강의 구조 설계를 바탕으로 슬라이드 초안을 작성하세요.\n"
        "원문 언어를 유지하고, 발표자 노트도 함께 포함해야 합니다.\n"
        f"커리큘럼 JSON:\n{curriculum_json}\n"
        f"{revise_text}"
        "출력은 슬라이드 JSON 배열이어야 합니다."
    )
