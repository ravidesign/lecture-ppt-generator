import hashlib
import os
import re
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image


QUERY_STOPWORDS = {
    "사용",
    "해주세요",
    "해줘",
    "부분",
    "파트",
    "내용",
    "위주",
    "중심",
    "쪽",
    "페이지",
    "장",
    "범위",
    "에서",
    "까지",
    "부터",
    "관련",
    "중",
    "전체",
    "only",
    "just",
    "use",
    "please",
    "part",
    "section",
    "pages",
    "page",
}

POSITION_HINTS = {
    "front": ("앞부분", "앞쪽", "초반", "서론", "도입", "초기"),
    "middle": ("중간", "중반"),
    "back": ("후반", "후반부", "뒷부분", "마지막", "결론", "끝부분"),
}


def get_total_pages(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def _normalize_pages(pages, total_pages: int) -> list[int]:
    if not pages:
        return []
    return sorted({int(page) for page in pages if 1 <= int(page) <= total_pages})


def _normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^\w\s가-힣]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact_text(text: str) -> str:
    return _normalize_text(text).replace(" ", "")


def parse_page_range(page_range: str, total_pages: int) -> list[int]:
    """숫자 기반 범위를 폭넓게 해석한다.

    예:
    - "1-5, 8, 10-12"
    - "3장부터 7장"
    - "1, 4, 9쪽"
    """
    text = str(page_range or "").strip()
    if not text:
        return []

    pages = set()
    unit = r"(?:쪽|페이지|장|page|pages|p)?"
    range_pattern = re.compile(
        rf"(\d+)\s*{unit}\s*(?:-|~|부터|에서|to)\s*(\d+)\s*{unit}",
        re.IGNORECASE,
    )
    consumed = []

    for match in range_pattern.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= end:
            pages.update(range(start, end + 1))
        else:
            pages.update(range(end, start + 1))
        consumed.append(match.span())

    leftovers = []
    cursor = 0
    for start, end in consumed:
        leftovers.append(text[cursor:start])
        cursor = end
    leftovers.append(text[cursor:])
    remainder = " ".join(leftovers)

    for match in re.finditer(
        rf"(?<!\d)(\d+)\s*{unit}(?!\d)",
        remainder,
        re.IGNORECASE,
    ):
        pages.add(int(match.group(1)))

    return _normalize_pages(pages, total_pages)


def _extract_page_texts(pdf_path: str) -> list[str]:
    doc = fitz.open(pdf_path)
    try:
        return [page.get_text("text") or "" for page in doc]
    finally:
        doc.close()


def _extract_query_tokens(query: str) -> list[str]:
    normalized = _normalize_text(query)
    tokens = []
    for token in normalized.split():
        if token.isdigit():
            continue
        if len(token) < 2:
            continue
        if token in QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _pages_for_position_hint(total_pages: int, hint_key: str) -> list[int]:
    window = min(max(total_pages // 4, 12), 30)
    if hint_key == "front":
        return list(range(1, min(total_pages, window) + 1))
    if hint_key == "back":
        start = max(1, total_pages - window + 1)
        return list(range(start, total_pages + 1))
    center = max(total_pages // 2, 1)
    half = max(window // 2, 1)
    start = max(1, center - half)
    end = min(total_pages, center + half)
    return list(range(start, end + 1))


def select_pages_by_text_hint(pdf_path: str, page_hint: str, max_pages: int = 100) -> list[int]:
    text_hint = str(page_hint or "").strip()
    if not text_hint:
        return []

    page_texts = _extract_page_texts(pdf_path)
    total_pages = len(page_texts)
    if total_pages == 0:
        return []

    tokens = _extract_query_tokens(text_hint)
    normalized_hint = _normalize_text(text_hint)
    compact_hint = _compact_text(text_hint)
    scores = {}

    for hint_key, keywords in POSITION_HINTS.items():
        if any(keyword in text_hint for keyword in keywords):
            for page in _pages_for_position_hint(total_pages, hint_key):
                scores[page] = scores.get(page, 0) + 4

    for page_index, raw_text in enumerate(page_texts, start=1):
        normalized_page = _normalize_text(raw_text)
        compact_page = _compact_text(raw_text)
        score = scores.get(page_index, 0)

        if normalized_hint and len(normalized_hint) >= 2 and normalized_hint in normalized_page:
            score += 10
        if compact_hint and len(compact_hint) >= 2 and compact_hint in compact_page:
            score += 8

        for token in tokens:
            if token in normalized_page:
                score += min(normalized_page.count(token), 5) * 2
            if token in compact_page:
                score += 1

        if score > 0:
            scores[page_index] = score

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    selected = []
    seen = set()

    for page, _score in ranked:
        neighbors = [page - 1, page, page + 1]
        for candidate in neighbors:
            if 1 <= candidate <= total_pages and candidate not in seen:
                selected.append(candidate)
                seen.add(candidate)
                if len(selected) >= max_pages:
                    return sorted(selected)

    return sorted(selected[:max_pages])


def resolve_page_selection(pdf_path: str, page_hint: str | None, max_pages_per_chunk: int = 100) -> dict:
    total_pages = get_total_pages(pdf_path)
    all_pages = list(range(1, total_pages + 1))
    hint = str(page_hint or "").strip()

    if not hint:
        return {
            "mode": "all",
            "page_hint": "",
            "selected_pages": all_pages,
            "total_pages": total_pages,
            "selection_note": "",
            "chunk_size": max_pages_per_chunk,
        }

    numeric_pages = parse_page_range(hint, total_pages)
    if numeric_pages:
        return {
            "mode": "numeric",
            "page_hint": hint,
            "selected_pages": numeric_pages,
            "total_pages": total_pages,
            "selection_note": f"사용자가 지정한 페이지 범위: {hint}",
            "chunk_size": max_pages_per_chunk,
        }

    text_pages = select_pages_by_text_hint(pdf_path, hint, max_pages=max_pages_per_chunk)
    if text_pages:
        return {
            "mode": "text",
            "page_hint": hint,
            "selected_pages": text_pages,
            "total_pages": total_pages,
            "selection_note": f"사용자 요청 파트: {hint}",
            "chunk_size": max_pages_per_chunk,
        }

    return {
        "mode": "hint_only",
        "page_hint": hint,
        "selected_pages": all_pages,
        "total_pages": total_pages,
        "selection_note": f"사용자 요청 파트: {hint}",
        "chunk_size": max_pages_per_chunk,
    }


def chunk_pages(page_numbers: list[int], chunk_size: int = 100) -> list[list[int]]:
    numbers = sorted(page_numbers)
    if not numbers:
        return []
    return [numbers[index:index + chunk_size] for index in range(0, len(numbers), chunk_size)]


def format_page_ranges(page_numbers: list[int]) -> str:
    numbers = sorted(page_numbers)
    if not numbers:
        return ""

    ranges = []
    start = prev = numbers[0]
    for page in numbers[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = page
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(ranges)


def extract_pages_as_bytes(pdf_path: str, page_spec=None) -> bytes:
    """지정 페이지를 포함한 PDF bytes 반환.

    page_spec:
    - None: 원본 전체
    - str: 숫자 범위 문자열
    - list[int]: 1-indexed page list
    """
    if page_spec is None:
        with open(pdf_path, "rb") as handle:
            return handle.read()

    doc = fitz.open(pdf_path)
    try:
        total = len(doc)
        if isinstance(page_spec, str):
            pages = parse_page_range(page_spec, total)
        else:
            pages = _normalize_pages(page_spec, total)

        if not pages or len(pages) == total:
            return doc.tobytes()

        new_doc = fitz.open()
        try:
            for page in pages:
                new_doc.insert_pdf(doc, from_page=page - 1, to_page=page - 1)
            return new_doc.tobytes()
        finally:
            new_doc.close()
    finally:
        doc.close()


def extract_pdf_images(
    pdf_path: str,
    page_numbers: list[int] | None,
    output_dir: str,
    bundle_uid: str,
    max_total: int = 24,
    max_per_page: int = 2,
    min_width: int = 160,
    min_height: int = 120,
    min_area: int = 32000,
) -> list[dict]:
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    assets = []
    seen_hashes = set()

    try:
        target_pages = list(range(1, len(doc) + 1)) if page_numbers is None else page_numbers
        pages = _normalize_pages(target_pages, len(doc))
        for page_number in pages:
            page = doc.load_page(page_number - 1)
            page_candidates = []

            for image_info in page.get_images(full=True):
                xref = image_info[0]
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue

                raw_bytes = extracted.get("image")
                if not raw_bytes:
                    continue

                raw_hash = hashlib.sha1(raw_bytes).hexdigest()
                if raw_hash in seen_hashes:
                    continue

                try:
                    with Image.open(BytesIO(raw_bytes)) as img:
                        width, height = img.size
                except Exception:
                    continue

                if width < min_width or height < min_height or (width * height) < min_area:
                    continue

                aspect_ratio = max(width / max(height, 1), height / max(width, 1))
                if aspect_ratio > 6:
                    continue

                rects = page.get_image_rects(xref)
                display_area = 0
                if rects:
                    display_area = max(int(rect.width * rect.height) for rect in rects)
                if display_area <= 0:
                    display_area = width * height

                page_candidates.append(
                    {
                        "hash": raw_hash,
                        "page": page_number,
                        "width": width,
                        "height": height,
                        "display_area": display_area,
                        "bytes": raw_bytes,
                    }
                )

            page_candidates.sort(
                key=lambda item: (
                    -item["display_area"],
                    -(item["width"] * item["height"]),
                    item["page"],
                )
            )

            for candidate in page_candidates[:max_per_page]:
                asset_index = len(assets) + 1
                asset_name = f"img_{asset_index:03d}.png"
                target_path = os.path.join(output_dir, asset_name)

                try:
                    with Image.open(BytesIO(candidate["bytes"])) as img:
                        converted = img.convert("RGBA") if "A" in img.getbands() else img.convert("RGB")
                        converted.save(target_path, format="PNG")
                except Exception:
                    continue

                seen_hashes.add(candidate["hash"])
                assets.append(
                    {
                        "bundle_uid": bundle_uid,
                        "asset_name": asset_name,
                        "page": candidate["page"],
                        "width": candidate["width"],
                        "height": candidate["height"],
                        "display_area": candidate["display_area"],
                    }
                )

                if len(assets) >= max_total:
                    return assets
    finally:
        doc.close()

    return assets
