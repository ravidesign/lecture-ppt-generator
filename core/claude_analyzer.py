import base64
import json
import os
import re
import unicodedata

import anthropic
import httpx

from core.pdf_parser import (
    chunk_pages,
    extract_pages_as_bytes,
    format_page_ranges,
    resolve_page_selection,
)

FINAL_SYSTEM_PROMPT = """You are an expert lecture-slide planner.
Return only a JSON array for a lecture deck structure based on the supplied document.
Do not return Markdown, code fences, or any explanatory text.

Schema:
[
  {"type":"title","title":"Lecture title","subtitle":"Subtitle"},
  {"type":"agenda","title":"Agenda","items":["Topic 1","Topic 2","Topic 3"]},
  {"type":"content","role":"content|chapter","section_title":"Major section title","title":"Slide title","subtitle":"Optional helper title","layout":"classic|split|card|highlight|process|compare|image_left|image_top|auto","content_kind":"explain|process|compare|case|data","image_mode":"hero|support|none","source_pages":"12-14","points":["Point 1","Point 2","Point 3"],"notes":"Presenter notes"},
  {"type":"summary","title":"Key Summary","points":["Summary 1","Summary 2","Summary 3"]}
]

Rules:
- Include exactly one title slide, one agenda slide, and one summary slide.
- Use the requested number of content slides, or if auto mode is used choose between 5 and 50 content slides based on document length.
- Keep each point short and clear, usually 3 to 5 points per content slide.
- Preserve the original document language in slide text.
- Every content slide must include presenter notes of 1 to 2 concise sentences.
- Every content slide must include role, section_title, layout, content_kind, image_mode, and source_pages fields.
- Mix layouts naturally instead of repeating the same layout everywhere.
- chapter slides are section-divider slides: title + short subtitle + at most one short point. Do not mix detailed bullets into chapter slides.
- content slides are normal teaching slides.
- classic: general explanation, split: section intro or case, card: short parallel items, highlight: one major takeaway, process: flow or steps, compare: contrast two perspectives, image_left/image_top: image-led slides where the image should be visually dominant.
- Set image_mode=hero only when the source pages contain a truly relevant image or diagram worth making visually dominant.
- Prefer pages with images, charts, or diagrams when assigning source_pages, but do not force an image onto every slide.
- If a topic marks a new major section, emit a chapter slide before the detailed content slides for that section.
- If a single idea would become too dense on one slide, split it into multiple content slides instead of cramming the text.
- The document may have been summarized in chunks already, so merge repeated themes and produce one coherent lecture flow.
"""

CHUNK_SYSTEM_PROMPT = """You are helping summarize one chunk of a long PDF for lecture design.
Return exactly one JSON object and nothing else.

Schema:
{
  "chunk_title": "Main chunk topic",
  "topics": ["Topic 1", "Topic 2", "Topic 3"],
  "key_points": ["Key point 1", "Key point 2", "Key point 3"],
  "section_titles": ["Section 1", "Section 2"],
  "teaching_focus": ["Focus point 1", "Focus point 2"]
}

Rules:
- Keep every list concise and non-duplicated.
- Usually return 3 to 8 items for each list.
- Preserve the original document language inside the content itself.
"""

NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
ANTHROPIC_CONNECT_TIMEOUT = 20.0
ANTHROPIC_READ_TIMEOUT = 660.0
ANTHROPIC_WRITE_TIMEOUT = 60.0
ANTHROPIC_POOL_TIMEOUT = 60.0
LECTURE_GOAL_HINTS = {
    "standard": "Build a balanced lecture deck for a normal class session.",
    "intro": "Optimize for first-time learners: define terms clearly, reduce jargon, and use intuitive explanations.",
    "exam": "Optimize for exam prep: emphasize definitions, distinctions, high-yield facts, and memorization-friendly summaries.",
    "practice": "Optimize for practical teaching: include workflows, applied examples, and step-by-step reasoning where relevant.",
    "theory": "Optimize for theory-heavy teaching: focus on principles, structures, mechanisms, and conceptual connections.",
    "briefing": "Optimize for a concise briefing: keep slides tighter, conclusion-oriented, and decision-friendly.",
}


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


def _contains_non_ascii(value: str | None) -> bool:
    return bool(value and NON_ASCII_RE.search(str(value)))


def _safe_user_instruction(value: str | None, fallback: str | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not _contains_non_ascii(text):
        return text
    return fallback


def _ensure_ascii_text(value: str | None, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not _contains_non_ascii(text):
        return text

    compact = text.encode("ascii", "ignore").decode("ascii").strip()
    return compact or fallback


def _sanitize_api_key(raw_value: str | None) -> str:
    text = str(raw_value or "")
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", text)
    no_format = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    no_space = "".join(ch for ch in no_format if not ch.isspace())
    stripped = no_space.strip().strip('"').strip("'")
    ascii_only = stripped.encode("ascii", "ignore").decode("ascii")
    return ascii_only


def _build_client() -> anthropic.Anthropic:
    raw_key = os.getenv("ANTHROPIC_API_KEY")
    api_key = _sanitize_api_key(raw_key)
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing or invalid after sanitization.")
    http_client = httpx.Client(
        trust_env=False,
        timeout=httpx.Timeout(
            connect=ANTHROPIC_CONNECT_TIMEOUT,
            read=ANTHROPIC_READ_TIMEOUT,
            write=ANTHROPIC_WRITE_TIMEOUT,
            pool=ANTHROPIC_POOL_TIMEOUT,
        ),
    )
    return anthropic.Anthropic(
        api_key=api_key,
        http_client=http_client,
        max_retries=2,
    )


def _build_slide_request(
    slide_count: int | None,
    page_plan: dict,
    extra_prompt: str | None,
    ascii_safe_mode: bool = False,
    lecture_goal: str | None = None,
) -> str:
    page_summary = format_page_ranges(page_plan["selected_pages"])
    if slide_count is None:
        slide_instruction = (
            "Choose the number of content slides automatically based on document length. "
            "Keep the number of content slides between 5 and 50."
        )
    else:
        slide_instruction = f"Create exactly {slide_count} content slides."

    lines = [
        "Analyze this document and produce a lecture-slide JSON array.",
        slide_instruction,
        f"Total PDF pages: {page_plan['total_pages']}",
        f"Pages included in this analysis: {len(page_plan['selected_pages'])}",
        "Use only the selected pages listed below.",
        "Do not use topics, examples, or sections from pages outside the selected page set.",
        "Keep the lecture tightly focused on the selected chapter/part instead of broadening back out to the whole PDF.",
        "Prefer a lecture-ready structure that uses images and diagrams from the PDF when helpful.",
    ]

    goal_hint = LECTURE_GOAL_HINTS.get(str(lecture_goal or "standard").strip().lower())
    if goal_hint:
        lines.append(f"Lecture goal: {goal_hint}")

    if page_summary:
        lines.append(f"Selected pages: {page_summary}")
    if page_plan.get("selection_note"):
        if ascii_safe_mode or _contains_non_ascii(page_plan.get("selection_note")):
            lines.append("A local topic-selection hint was applied before analysis. Stay tightly focused on the selected pages only.")
        else:
            lines.append(f"Page-selection note: {page_plan['selection_note']}")
    if extra_prompt and extra_prompt.strip():
        safe_prompt = _safe_user_instruction(
            extra_prompt.strip(),
            fallback="An additional non-ASCII UI instruction was supplied. Prioritize clarity, examples, and a lecture-friendly structure.",
        )
        if safe_prompt:
            lines.append(f"Additional instruction: {safe_prompt}")

    return "\n".join(lines)


def _message_text(message) -> str:
    blocks = getattr(message, "content", []) or []
    texts = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _request_pdf_json(client, pdf_bytes: bytes, system_prompt: str, user_text: str, max_tokens: int):
    safe_system_prompt = _ensure_ascii_text(
        system_prompt,
        fallback="You are an expert lecture-slide planner. Return only valid JSON.",
    )
    safe_user_text = _ensure_ascii_text(
        user_text,
        fallback="Analyze the supplied PDF and return the requested lecture-slide JSON array.",
    )
    with client.messages.stream(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        system=safe_system_prompt,
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
                        "text": safe_user_text,
                    },
                ],
            }
        ],
        timeout=httpx.Timeout(
            connect=ANTHROPIC_CONNECT_TIMEOUT,
            read=ANTHROPIC_READ_TIMEOUT,
            write=ANTHROPIC_WRITE_TIMEOUT,
            pool=ANTHROPIC_POOL_TIMEOUT,
        ),
    ) as stream:
        final_message = stream.get_final_message()
    return _load_json(_message_text(final_message))


def _request_text_json(client, system_prompt: str, user_text: str, max_tokens: int):
    safe_system_prompt = _ensure_ascii_text(
        system_prompt,
        fallback="You are an expert lecture-slide planner. Return only valid JSON.",
    )
    safe_user_text = _ensure_ascii_text(
        user_text,
        fallback="Combine the supplied chunk summaries into one lecture-slide JSON array.",
    )
    with client.messages.stream(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        system=safe_system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": safe_user_text}]}],
        timeout=httpx.Timeout(
            connect=ANTHROPIC_CONNECT_TIMEOUT,
            read=ANTHROPIC_READ_TIMEOUT,
            write=ANTHROPIC_WRITE_TIMEOUT,
            pool=ANTHROPIC_POOL_TIMEOUT,
        ),
    ) as stream:
        final_message = stream.get_final_message()
    return _load_json(_message_text(final_message))


def _summarize_large_pdf(
    client,
    pdf_path: str,
    page_plan: dict,
    extra_prompt: str | None,
    ascii_safe_mode: bool = False,
    lecture_goal: str | None = None,
) -> list[dict]:
    chunk_summaries = []
    for chunk_index, pages in enumerate(chunk_pages(page_plan["selected_pages"], page_plan["chunk_size"]), start=1):
        chunk_pdf = extract_pages_as_bytes(pdf_path, pages)
        chunk_text = (
            f"This PDF chunk corresponds to pages {format_page_ranges(pages)} from the original document.\n"
            f"The full document has {page_plan['total_pages']} pages.\n"
            "Summarize this chunk into JSON for lecture planning.\n"
            "Stay focused on the selected pages only and do not reintroduce topics from excluded parts of the PDF."
        )
        goal_hint = LECTURE_GOAL_HINTS.get(str(lecture_goal or "standard").strip().lower())
        if goal_hint:
            chunk_text += f"\nLecture goal: {goal_hint}"
        if page_plan.get("selection_note"):
            if ascii_safe_mode or _contains_non_ascii(page_plan.get("selection_note")):
                chunk_text += "\nA local topic-selection hint was applied before chunk analysis. Remain tightly scoped to the selected chapter/part."
            else:
                chunk_text += f"\nPage-selection note: {page_plan['selection_note']}"
        if extra_prompt and extra_prompt.strip():
            safe_prompt = _safe_user_instruction(
                extra_prompt.strip(),
                fallback="A non-ASCII additional instruction was supplied in the UI. Favor clarity, examples, and a lecture-friendly structure.",
            )
            if safe_prompt:
                chunk_text += f"\nAdditional instruction: {safe_prompt}"

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
    ascii_safe_mode: bool = False,
    page_plan: dict | None = None,
    lecture_goal: str | None = None,
) -> list:
    """PDF → Claude API → 슬라이드 JSON"""
    client = _build_client()
    page_plan = page_plan or resolve_page_selection(pdf_path, page_range, max_pages_per_chunk=100)

    if len(page_plan["selected_pages"]) <= page_plan["chunk_size"]:
        pdf_bytes = extract_pages_as_bytes(pdf_path, page_plan["selected_pages"])
        user_text = _build_slide_request(
            slide_count,
            page_plan,
            extra_prompt,
            ascii_safe_mode=ascii_safe_mode,
            lecture_goal=lecture_goal,
        )
        return _request_pdf_json(client, pdf_bytes, FINAL_SYSTEM_PROMPT, user_text, max_tokens=12000)

    chunk_summaries = _summarize_large_pdf(
        client,
        pdf_path,
        page_plan,
        extra_prompt,
        ascii_safe_mode=ascii_safe_mode,
        lecture_goal=lecture_goal,
    )
    slide_request = _build_slide_request(
        slide_count,
        page_plan,
        extra_prompt,
        ascii_safe_mode=ascii_safe_mode,
        lecture_goal=lecture_goal,
    )
    final_text = (
        f"{slide_request}\n\n"
        "Below are chunked lecture-planning summaries from the same PDF. "
        "Combine them into one final lecture-slide JSON array.\n\n"
        f"{json.dumps(chunk_summaries, ensure_ascii=True)}"
    )
    return _request_text_json(client, FINAL_SYSTEM_PROMPT, final_text, max_tokens=12000)
