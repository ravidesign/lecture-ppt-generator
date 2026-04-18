from __future__ import annotations


def build_factcheck_task(curriculum_json: str, slides_json: str, source_excerpt: str) -> str:
    return (
        "아래 슬라이드 초안을 원문과 대조하여 PASS, REVISE, REJECT 중 하나로 판정하세요.\n"
        "누락, 오탈자, 원문 외 임의 추가, 수치 오류를 특히 엄격히 봐야 합니다.\n"
        f"커리큘럼:\n{curriculum_json}\n\n"
        f"슬라이드 초안:\n{slides_json}\n\n"
        f"원문 발췌:\n{source_excerpt}\n"
        "출력은 status, issues, revision_request를 포함한 JSON 객체여야 합니다."
    )
