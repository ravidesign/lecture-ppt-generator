import base64
import json
import os

import anthropic

from core.pdf_parser import (
    chunk_pages,
    extract_pages_as_bytes,
    format_page_ranges,
    resolve_page_selection,
)

FINAL_SYSTEM_PROMPT = """당신은 전문 강의 교안 설계자입니다.
제공된 문서 분석 결과를 바탕으로 강의용 슬라이드 구조를 JSON 배열로만 반환하세요.

반드시 아래 형식의 JSON 배열만 반환하세요. 코드블록(```), 설명 텍스트 절대 금지.

스키마:
[
  {"type":"title","title":"강의 제목","subtitle":"부제목"},
  {"type":"agenda","title":"목차","items":["주제1","주제2","주제3"]},
  {"type":"content","title":"슬라이드 제목","subtitle":"선택적 보조 제목","layout":"classic|split|card|highlight|process|compare|auto","source_pages":"12-14","points":["핵심 포인트1","핵심 포인트2","핵심 포인트3"],"notes":"발표자 노트"},
  {"type":"summary","title":"핵심 요약","points":["요약1","요약2","요약3"]}
]

규칙:
- title 슬라이드 1장
- agenda 슬라이드 1장
- summary 슬라이드 1장
- content 슬라이드는 사용자 요청 개수에 맞추거나, 자동 모드라면 문서 분량에 맞게 5장 이상 50장 이하로 결정
- 포인트는 3-5개, 각 포인트는 최대한 짧고 명확하게
- PDF 원문 언어 그대로 사용
- 발표자 노트는 모든 content 슬라이드에 필수이며 1-2문장으로 간결하게 작성
- 모든 content 슬라이드에는 반드시 layout 필드를 넣고, 슬라이드 내용 전달 방식에 맞게 classic / split / card / highlight / process / compare / auto 중 하나를 선택
- 모든 content 슬라이드에는 반드시 source_pages 필드를 넣고, 이 슬라이드가 주로 참고한 PDF 페이지 범위를 `12-14` 같은 형식으로 적기
- 같은 자료라도 모든 content 슬라이드에 같은 layout을 반복하지 말고, 설명 구조에 따라 자연스럽게 섞어서 사용
- classic: 일반 설명형, split: 섹션 소개/사례형, card: 4-5개의 짧고 병렬적인 항목, highlight: 가장 중요한 한 문장을 크게 강조, process: 절차/단계/플로우 설명, compare: 두 관점 비교
- 적절한 레이아웃이 명확하지 않으면 auto 사용
- 별도 지시가 없으면 PDF에 들어 있는 이미지나 도표를 강의 슬라이드에서 활용하기 좋은 페이지를 source_pages로 우선 지정
- 큰 문서는 여러 청크 요약을 종합한 결과일 수 있으므로 중복 없이 구조화
"""

CHUNK_SYSTEM_PROMPT = """당신은 긴 PDF를 여러 구간으로 나눠 분석하는 강의 설계 보조자입니다.
입력된 PDF 구간을 읽고 아래 JSON 객체 하나만 반환하세요. 코드블록이나 설명은 금지합니다.

스키마:
{
  "chunk_title": "이 구간의 제목 또는 핵심 주제",
  "topics": ["주제1", "주제2", "주제3"],
  "key_points": ["핵심 요점1", "핵심 요점2", "핵심 요점3"],
  "section_titles": ["섹션명1", "섹션명2"],
  "teaching_focus": ["강의에서 강조할 포인트1", "강의에서 강조할 포인트2"]
}

규칙:
- topics, key_points, section_titles, teaching_focus는 각각 3-8개
- 중복 없이 간결하게
- PDF 원문 언어 그대로 유지
"""


def _load_json(raw_text: str):
    clean = raw_text.replace("```json", "").replace("```", "").strip()
    # JSON 배열/객체 시작 위치 추출 (앞뒤 설명 텍스트 제거)
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = clean.find(start_char)
        end = clean.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            candidate = clean[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    return json.loads(clean)


def _encode_pdf_bytes(pdf_bytes: bytes) -> str:
    return base64.standard_b64encode(pdf_bytes).decode("utf-8")


def _build_slide_request(slide_count: int | None, page_plan: dict, extra_prompt: str | None) -> str:
    page_summary = format_page_ranges(page_plan["selected_pages"])
    if slide_count is None:
        slide_instruction = (
            "content 슬라이드는 문서 분량에 맞게 자동으로 정해주세요. "
            "단, content 슬라이드는 5장 이상 50장 이하로 구성해주세요."
        )
    else:
        slide_instruction = f"content 슬라이드는 {slide_count}장으로 만들어주세요."

    lines = [
        "이 자료를 분석해서 강의 교안 슬라이드 JSON을 만들어주세요.",
        slide_instruction,
        f"원본 PDF 전체 페이지 수: {page_plan['total_pages']}",
        f"이번 분석에 실제 반영된 페이지 수: {len(page_plan['selected_pages'])}",
        "별도 지시가 없으면 PDF에 포함된 이미지와 도표를 활용하는 강의 자료를 기본값으로 간주해주세요.",
    ]

    if page_summary:
        lines.append(f"분석 대상 페이지: {page_summary}")
    if page_plan.get("selection_note"):
        lines.append(page_plan["selection_note"])
    if extra_prompt and extra_prompt.strip():
        lines.append(f"추가 지시사항: {extra_prompt.strip()}")

    return "\n".join(lines)


def _request_pdf_json(client, pdf_bytes: bytes, system_prompt: str, user_text: str, max_tokens: int):
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": _encode_pdf_bytes(pdf_bytes),
                        },
                    },
                    {
                        "type": "text",
                        "text": user_text,
                    },
                ],
            }
        ],
    )
    return _load_json(response.content[0].text.strip())


def _request_text_json(client, system_prompt: str, user_text: str, max_tokens: int):
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_text}]}],
    )
    return _load_json(response.content[0].text.strip())


def _summarize_large_pdf(client, pdf_path: str, page_plan: dict, extra_prompt: str | None) -> list[dict]:
    chunk_summaries = []
    for chunk_index, pages in enumerate(chunk_pages(page_plan["selected_pages"], page_plan["chunk_size"]), start=1):
        chunk_pdf = extract_pages_as_bytes(pdf_path, pages)
        chunk_text = (
            f"이 PDF는 원본 문서의 {format_page_ranges(pages)} 페이지에 해당하는 구간입니다.\n"
            f"원본 전체 페이지 수는 {page_plan['total_pages']}입니다.\n"
            f"이 구간을 요약해서 강의 설계에 쓸 핵심 정보를 JSON으로 정리해주세요."
        )
        if page_plan.get("selection_note"):
            chunk_text += f"\n사용자 요청 맥락: {page_plan['selection_note']}"
        if extra_prompt and extra_prompt.strip():
            chunk_text += f"\n추가 지시사항: {extra_prompt.strip()}"

        chunk_summary = _request_pdf_json(
            client,
            chunk_pdf,
            CHUNK_SYSTEM_PROMPT,
            chunk_text,
            max_tokens=2500,
        )
        chunk_summaries.append(
            {
                "chunk_index": chunk_index,
                "pages": format_page_ranges(pages),
                "summary": chunk_summary,
            }
        )
    return chunk_summaries


def analyze_pdf(
    pdf_path: str,
    slide_count: int | None = 10,
    page_range: str = None,
    extra_prompt: str = None,
) -> list:
    """PDF → Claude API → 슬라이드 JSON"""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    page_plan = resolve_page_selection(pdf_path, page_range, max_pages_per_chunk=100)

    if len(page_plan["selected_pages"]) <= page_plan["chunk_size"]:
        pdf_bytes = extract_pages_as_bytes(pdf_path, page_plan["selected_pages"])
        user_text = _build_slide_request(slide_count, page_plan, extra_prompt)
        return _request_pdf_json(client, pdf_bytes, FINAL_SYSTEM_PROMPT, user_text, max_tokens=12000)

    chunk_summaries = _summarize_large_pdf(client, pdf_path, page_plan, extra_prompt)
    slide_request = _build_slide_request(slide_count, page_plan, extra_prompt)
    final_text = (
        f"{slide_request}\n\n"
        "아래는 긴 PDF를 100페이지 이하 청크로 나눠 분석한 결과입니다. "
        "이 결과를 종합해서 최종 강의 교안 슬라이드 JSON 배열을 만들어주세요.\n\n"
        f"{json.dumps(chunk_summaries, ensure_ascii=False)}"
    )
    return _request_text_json(client, FINAL_SYSTEM_PROMPT, final_text, max_tokens=12000)
