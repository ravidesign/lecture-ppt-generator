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

QUERY_TRAILING_SUFFIXES = (
    "만이라도",
    "만으로",
    "만요",
    "만은",
    "만을",
    "만",
    "위주로",
    "위주",
    "중심으로",
    "중심",
    "부분만",
    "파트만",
    "부분",
    "파트",
    "내용만",
    "내용",
    "관련",
    "쪽",
    "범위",
    "사용",
)

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


def _strip_query_suffixes(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return ""

    for _ in range(4):
        updated = cleaned
        for suffix in QUERY_TRAILING_SUFFIXES:
            if len(updated) > len(suffix) + 1 and updated.endswith(suffix):
                updated = updated[: -len(suffix)]
                break
        if updated == cleaned:
            break
        cleaned = updated.strip()

    return cleaned


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


def _first_heading_from_text(text: str) -> str:
    for raw_line in str(text or "").splitlines()[:18]:
        line = " ".join(raw_line.split()).strip()
        if len(line) < 3:
            continue
        if re.fullmatch(r"[\d\s./-]+", line):
            continue
        return line[:120]
    return ""


def _sample_preview_pages(page_numbers: list[int], max_items: int = 6) -> list[int]:
    numbers = sorted({int(page) for page in page_numbers if int(page) >= 1})
    if len(numbers) <= max_items:
        return numbers

    if max_items <= 1:
        return [numbers[0]]

    sampled = []
    last_index = len(numbers) - 1
    for step in range(max_items):
        index = round((last_index * step) / (max_items - 1))
        sampled.append(numbers[index])
    return sorted(dict.fromkeys(sampled))


def _extract_query_tokens(query: str) -> list[str]:
    normalized = _normalize_text(query)
    tokens = []
    for token in normalized.split():
        token = _strip_query_suffixes(token)
        if token.isdigit():
            continue
        if len(token) < 2:
            continue
        if token in QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _extract_query_phrases(query: str) -> list[str]:
    tokens = _extract_query_tokens(query)
    if not tokens:
        return []

    phrases = []
    joined = " ".join(tokens).strip()
    compact = "".join(tokens).strip()
    if len(joined) >= 2:
        phrases.append(joined)
    if len(compact) >= 2 and compact != joined:
        phrases.append(compact)

    if len(tokens) >= 2:
        for size in (2, 3):
            if len(tokens) < size:
                continue
            for index in range(len(tokens) - size + 1):
                chunk = tokens[index:index + size]
                joined_chunk = " ".join(chunk).strip()
                compact_chunk = "".join(chunk).strip()
                if len(joined_chunk) >= 2:
                    phrases.append(joined_chunk)
                if len(compact_chunk) >= 2 and compact_chunk != joined_chunk:
                    phrases.append(compact_chunk)

    seen = set()
    unique = []
    for phrase in phrases:
        if phrase in seen:
            continue
        seen.add(phrase)
        unique.append(phrase)
    return unique


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
    phrases = _extract_query_phrases(text_hint)
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
        leading_page = " ".join(normalized_page.split()[:60])
        score = scores.get(page_index, 0)

        if normalized_hint and len(normalized_hint) >= 2 and normalized_hint in normalized_page:
            score += 10
        if compact_hint and len(compact_hint) >= 2 and compact_hint in compact_page:
            score += 8

        for phrase in phrases:
            if phrase in normalized_page:
                score += 16
            compact_phrase = phrase.replace(" ", "")
            if compact_phrase and compact_phrase in compact_page:
                score += 14
            if phrase in leading_page:
                score += 10

        for token in tokens:
            if token in normalized_page:
                score += min(normalized_page.count(token), 6) * 4
            if token in compact_page:
                score += 2
            if token in leading_page:
                score += 3

        if score > 0:
            scores[page_index] = score

    if not scores:
        return []

    scored_pages = sorted(scores)
    clusters = []
    current_cluster = [scored_pages[0]]
    for page in scored_pages[1:]:
        if page - current_cluster[-1] <= 2:
            current_cluster.append(page)
        else:
            clusters.append(current_cluster)
            current_cluster = [page]
    clusters.append(current_cluster)

    def cluster_rank(cluster_pages: list[int]):
        start = cluster_pages[0]
        end = cluster_pages[-1]
        span = max(end - start + 1, 1)
        hit_count = len(cluster_pages)
        total_score = sum(scores.get(page, 0) for page in cluster_pages)
        density = total_score / span
        phrase_hits = sum(1 for page in cluster_pages if scores.get(page, 0) >= 18)
        continuity_bonus = max(0, hit_count - 1) * 1.6
        fragmentation_penalty = max(0, span - hit_count) * 2.1
        broad_range_penalty = max(0, span - max_pages) * 3.5
        strength = total_score + phrase_hits * 10 + continuity_bonus - fragmentation_penalty - broad_range_penalty
        return (-strength, -density, -total_score, start)

    best_cluster = min(clusters, key=cluster_rank)
    cluster_start = best_cluster[0]
    cluster_end = best_cluster[-1]
    start = max(1, cluster_start - 1)
    end = min(total_pages, cluster_end + 1)
    focus_span = min(max_pages, max(8, min(22, 8 + len(tokens) * 4)))

    if (end - start + 1) > focus_span:
        best_window = (start, min(total_pages, start + focus_span - 1))
        best_window_score = None
        for window_start in range(start, end - focus_span + 2):
            window_end = window_start + focus_span - 1
            window_score = sum(scores.get(page, 0) for page in range(window_start, window_end + 1))
            if best_window_score is None or window_score > best_window_score:
                best_window = (window_start, window_end)
                best_window_score = window_score
        start, end = best_window

    if (end - start + 1) > max_pages:
        end = start + max_pages - 1

    return list(range(start, end + 1))


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


def build_page_plan_preview(pdf_path: str, page_plan: dict, max_headings: int = 6) -> dict:
    selected_pages = sorted({int(page) for page in (page_plan or {}).get("selected_pages", []) if int(page) >= 1})
    total_pages = int((page_plan or {}).get("total_pages") or 0)
    if not selected_pages or total_pages <= 0:
        return {
            "mode": str((page_plan or {}).get("mode") or "all"),
            "page_summary": "",
            "selected_count": 0,
            "selection_note": str((page_plan or {}).get("selection_note") or ""),
            "headings": [],
            "warning": "선택된 페이지 정보를 확인할 수 없습니다.",
        }

    doc = fitz.open(pdf_path)
    try:
        headings = []
        for page_number in _sample_preview_pages(selected_pages, max_items=max_headings):
            try:
                text = doc.load_page(page_number - 1).get_text("text") or ""
            except Exception:
                text = ""
            heading = _first_heading_from_text(text)
            headings.append(
                {
                    "page": page_number,
                    "heading": heading or f"{page_number}페이지 내용",
                }
            )
    finally:
        doc.close()

    mode = str((page_plan or {}).get("mode") or "all")
    warning = ""
    if mode == "hint_only":
        warning = "요청 문구를 정확히 매칭하지 못해 전체 PDF 범위를 사용할 가능성이 높습니다. 분석 전에 범위를 다시 확인해 주세요."
    elif mode == "all" and str((page_plan or {}).get("page_hint") or "").strip():
        warning = "요청 문구가 범위 제한으로 이어지지 않아 전체 PDF 범위를 사용할 예정입니다."

    return {
        "mode": mode,
        "page_summary": format_page_ranges(selected_pages),
        "selected_count": len(selected_pages),
        "selection_note": str((page_plan or {}).get("selection_note") or ""),
        "headings": headings,
        "warning": warning,
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


def _trim_rendered_image(image_bytes: bytes, tolerance: int = 245, margin: int = 6) -> bytes:
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            pixels = rgb.load()
            left, top = width, height
            right = bottom = -1

            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    if min(r, g, b) < tolerance:
                        left = min(left, x)
                        top = min(top, y)
                        right = max(right, x)
                        bottom = max(bottom, y)

            if right < left or bottom < top:
                return image_bytes

            crop_box = (
                max(0, left - margin),
                max(0, top - margin),
                min(width, right + margin + 1),
                min(height, bottom + margin + 1),
            )
            if crop_box == (0, 0, width, height):
                return image_bytes

            cropped = rgb.crop(crop_box)
            buffer = BytesIO()
            cropped.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception:
        return image_bytes


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
            page_area = max(float(page.rect.width * page.rect.height), 1.0)
            page_text = " ".join((page.get_text("text") or "").split())
            page_text_hint = page_text[:600]
            page_heading = ""
            for raw_line in page_text.splitlines():
                line = raw_line.strip()
                if len(line) >= 3:
                    page_heading = line[:120]
                    break

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
                main_rect = None
                if rects:
                    main_rect = max(rects, key=lambda rect: rect.width * rect.height)
                    display_area = int(main_rect.width * main_rect.height)
                if display_area <= 0:
                    display_area = width * height

                coverage_ratio = display_area / page_area
                if coverage_ratio < 0.012 and display_area < 18000:
                    continue

                clip_bytes = raw_bytes
                clip_width = width
                clip_height = height
                if main_rect is not None:
                    try:
                        pad_x = max(main_rect.width * 0.05, 8)
                        pad_y = max(main_rect.height * 0.05, 8)
                        clip_rect = fitz.Rect(
                            max(page.rect.x0, main_rect.x0 - pad_x),
                            max(page.rect.y0, main_rect.y0 - pad_y),
                            min(page.rect.x1, main_rect.x1 + pad_x),
                            min(page.rect.y1, main_rect.y1 + pad_y),
                        )
                        pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), clip=clip_rect, alpha=False)
                        rendered_bytes = pix.tobytes("png")
                        rendered_bytes = _trim_rendered_image(rendered_bytes)
                        with Image.open(BytesIO(rendered_bytes)) as rendered_img:
                            clip_width, clip_height = rendered_img.size
                        clip_bytes = rendered_bytes
                    except Exception:
                        clip_bytes = raw_bytes
                        clip_width = width
                        clip_height = height

                asset_hash = hashlib.sha1(clip_bytes).hexdigest()
                if asset_hash in seen_hashes:
                    continue

                page_candidates.append(
                    {
                        "hash": asset_hash,
                        "page": page_number,
                        "width": clip_width,
                        "height": clip_height,
                        "display_area": display_area,
                        "coverage_ratio": round(coverage_ratio, 6),
                        "bytes": clip_bytes,
                    }
                )

            page_candidates.sort(
                key=lambda item: (
                    -item["coverage_ratio"],
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
                        "coverage_ratio": candidate["coverage_ratio"],
                        "page_heading": page_heading,
                        "page_text_hint": page_text_hint,
                    }
                )

                if len(assets) >= max_total:
                    return assets
    finally:
        doc.close()

    return assets
