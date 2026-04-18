from __future__ import annotations


def build_layout_task(slides_json: str, asset_summary: str) -> str:
    return (
        "슬라이드별 레이아웃과 이미지 사용 전략을 검토하세요.\n"
        "챕터/내용/요약 슬라이드 역할을 유지하고, 이미지가 중요한 페이지는 더 크게 보이게 해야 합니다.\n"
        f"슬라이드 JSON:\n{slides_json}\n\n"
        f"추출 이미지 요약:\n{asset_summary}\n"
        "출력은 slide_overrides 배열 JSON 객체여야 하며, 각 항목은 slide_index, layout, image_mode, note를 포함할 수 있습니다."
    )
