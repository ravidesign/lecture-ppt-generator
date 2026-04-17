from __future__ import annotations

import re
from copy import deepcopy

from core.pdf_parser import parse_page_range


PAGE_NUMBER_RE = re.compile(r"\d+")
WORD_RE = re.compile(r"[A-Za-z0-9가-힣]{2,}")
STOPWORDS = {
    "the",
    "and",
    "slide",
    "lecture",
    "자료",
    "설명",
    "핵심",
    "내용",
    "정리",
    "개요",
    "기본",
    "사용",
}
VALID_IMAGE_CHOICE_MODES = {"auto", "manual", "manual_none"}


def _asset_key(asset: dict) -> tuple[str, str]:
    return str(asset.get("bundle_uid") or ""), str(asset.get("asset_name") or "")


def _slide_key(slide: dict) -> tuple[str, str]:
    return str(slide.get("image_bundle_uid") or ""), str(slide.get("image_asset_name") or "")


def _parse_source_pages(source_pages: str, max_page: int) -> list[int]:
    source = str(source_pages or "").strip()
    if not source:
        return []

    fallback_max = max([max_page, *[int(match) for match in PAGE_NUMBER_RE.findall(source)]], default=max_page)
    parsed = parse_page_range(source, max(fallback_max, 1))
    if parsed:
        return parsed
    return [int(match) for match in PAGE_NUMBER_RE.findall(source)]


def _asset_quality_bucket(asset: dict) -> int:
    coverage = float(asset.get("coverage_ratio") or 0)
    display_area = int(asset.get("display_area") or 0)
    if coverage >= 0.10 or display_area >= 110000:
        return 0
    if coverage >= 0.045 or display_area >= 56000:
        return 1
    if coverage >= 0.025 or display_area >= 28000:
        return 2
    return 3


def _asset_is_usable(asset: dict) -> bool:
    return _asset_quality_bucket(asset) <= 2


def _tokenize(text: str) -> list[str]:
    tokens = []
    for match in WORD_RE.findall(str(text or "").lower()):
        token = match.strip()
        if not token or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _slide_keywords(slide: dict) -> set[str]:
    texts = [
        slide.get("title", ""),
        slide.get("subtitle", ""),
        slide.get("section_title", ""),
        " ".join(slide.get("points", []) or []),
        slide.get("notes", ""),
    ]
    words = set()
    for text in texts:
        words.update(_tokenize(text))
    return words


def _slide_text_total_chars(slide: dict) -> int:
    return sum(len(str(point).strip()) for point in (slide.get("points", []) or []) if str(point).strip())


def _asset_text(asset: dict) -> str:
    return " ".join(
        [
            str(asset.get("page_heading") or ""),
            str(asset.get("page_text_hint") or ""),
        ]
    ).strip()


def _asset_text_score(asset: dict, slide_keywords: set[str]) -> int:
    if not slide_keywords:
        return 0
    asset_tokens = set(_tokenize(_asset_text(asset)))
    if not asset_tokens:
        return 0
    overlap = slide_keywords & asset_tokens
    if not overlap:
        return 0
    return len(overlap) * 3


def _image_orientation(asset: dict | None) -> str:
    width = float((asset or {}).get("width") or 0)
    height = float((asset or {}).get("height") or 0)
    if width <= 0 or height <= 0:
        return "square"
    ratio = width / height
    if ratio >= 1.3:
        return "landscape"
    if ratio <= 0.82:
        return "portrait"
    return "square"


def _image_choice_mode(slide: dict) -> str:
    mode = str(slide.get("image_choice_mode") or "auto").strip().lower()
    return mode if mode in VALID_IMAGE_CHOICE_MODES else "auto"


def _clear_slide_image(slide: dict):
    slide.pop("image_bundle_uid", None)
    slide.pop("image_asset_name", None)
    slide.pop("image_page", None)
    slide["image_relevance"] = "none"
    slide["image_mode"] = "none"
    slide["image_orientation"] = ""


def _relevance_label(asset: dict, source_pages: list[int], slide_keywords: set[str]) -> str:
    if not asset:
        return "none"

    asset_page = int(asset.get("page") or 0)
    quality_bucket = _asset_quality_bucket(asset)
    overlap_score = _asset_text_score(asset, slide_keywords)
    exact = asset_page in source_pages if source_pages else False
    near = min((abs(asset_page - page) for page in source_pages), default=99) <= 1 if source_pages else False

    if exact and quality_bucket <= 1 and overlap_score >= 3:
        return "high"
    if (exact or near) and quality_bucket <= 2 and overlap_score >= 1:
        return "medium"
    if exact and quality_bucket == 0:
        return "medium"
    if exact and quality_bucket <= 1:
        return "medium"
    if exact and quality_bucket == 0 and not slide_keywords:
        return "medium"
    if exact and quality_bucket <= 1 and overlap_score >= 1:
        return "medium"
    if exact and overlap_score == 0 and slide_keywords:
        return "low"
    if near and overlap_score >= 1:
        return "low"
    return "none"


def _image_mode_for_slide(slide: dict, asset: dict | None, relevance: str) -> str:
    if not asset or relevance == "none":
        return "none"

    kind = str(slide.get("content_kind") or "").lower()
    point_count = len(slide.get("points", []) or [])
    total_chars = _slide_text_total_chars(slide)
    quality_bucket = _asset_quality_bucket(asset)
    if relevance in {"low", "medium", "high"} and quality_bucket <= 1 and point_count <= 2 and total_chars <= 140:
        return "hero"
    if relevance == "high" and quality_bucket <= 1:
        return "hero"
    if relevance == "medium" and quality_bucket == 0 and point_count <= 4:
        return "hero"
    if relevance in {"high", "medium"} and point_count <= 3 and kind not in {"compare"}:
        return "hero"
    if relevance in {"high", "medium"} and kind in {"compare", "process"} and quality_bucket <= 1:
        return "hero"
    if relevance == "medium" and kind in {"compare", "process", "data"}:
        return "support"
    if relevance == "low" and quality_bucket <= 1 and point_count <= 3 and total_chars <= 180:
        return "support"
    return "support"


def _should_keep_low_relevance_asset(slide: dict, asset: dict | None, source_pages: list[int], slide_keywords: set[str]) -> bool:
    if not asset:
        return False

    asset_page = int(asset.get("page") or 0)
    quality_bucket = _asset_quality_bucket(asset)
    point_count = len(slide.get("points", []) or [])
    total_chars = _slide_text_total_chars(slide)
    exact = asset_page in source_pages if source_pages else False
    near = min((abs(asset_page - page) for page in source_pages), default=99) <= 1 if source_pages else False
    overlap_score = _asset_text_score(asset, slide_keywords)

    if exact and quality_bucket <= 1 and point_count <= 3 and total_chars <= 180:
        return True
    if exact and quality_bucket == 0 and point_count <= 4 and total_chars <= 220:
        return True
    if near and quality_bucket == 0 and point_count <= 2 and overlap_score >= 1:
        return True
    return False


def _asset_score(asset: dict, source_pages: list[int], fallback_index: int, slide_keywords: set[str]) -> tuple[int, int, int, int, int]:
    asset_page = int(asset.get("page") or 0)
    quality_bucket = _asset_quality_bucket(asset)
    overlap_score = _asset_text_score(asset, slide_keywords)

    if source_pages:
        if asset_page in source_pages:
            distance = 0
        else:
            distance = min(abs(asset_page - page) for page in source_pages)
        exact_match = 0 if asset_page in source_pages else 1
        text_penalty = 0 if overlap_score >= 3 else (1 if overlap_score >= 1 else 2)
        return (exact_match, distance, text_penalty, quality_bucket, fallback_index)

    text_penalty = 0 if overlap_score >= 3 else (1 if overlap_score >= 1 else 2)
    return (2, text_penalty, quality_bucket, abs(fallback_index), asset_page)


def attach_pdf_images_to_slides(slides_data: list[dict], media_assets: list[dict] | None) -> list[dict]:
    slides = deepcopy(slides_data or [])
    assets = [dict(asset) for asset in (media_assets or []) if asset.get("bundle_uid") and asset.get("asset_name")]
    if not slides or not assets:
        return slides

    assets_by_key = {_asset_key(asset): asset for asset in assets}
    ordered_assets = sorted(
        assets_by_key.values(),
        key=lambda asset: (
            int(asset.get("page") or 0),
            str(asset.get("asset_name") or ""),
        ),
    )
    if not ordered_assets:
        return slides

    max_page = max(int(asset.get("page") or 0) for asset in ordered_assets) or 1
    used_asset_keys = {
        _slide_key(slide)
        for slide in slides
        if _slide_key(slide) in assets_by_key
    }

    for content_index, slide in enumerate(slides):
        if slide.get("type", "content") != "content":
            continue
        if str(slide.get("role") or "content").lower() == "chapter":
            slide["image_mode"] = "none"
            slide["image_relevance"] = "none"
            continue

        choice_mode = _image_choice_mode(slide)
        if choice_mode == "manual_none":
            _clear_slide_image(slide)
            slide["image_choice_mode"] = "manual_none"
            continue

        source_pages = _parse_source_pages(slide.get("source_pages", ""), max_page)
        slide_keywords = _slide_keywords(slide)
        current_key = _slide_key(slide)
        chosen_asset = assets_by_key.get(current_key)
        relevance = _relevance_label(chosen_asset, source_pages, slide_keywords) if chosen_asset else "none"

        if choice_mode == "manual":
            if chosen_asset:
                mode_relevance = relevance if relevance in {"high", "medium"} else "medium"
                slide["image_bundle_uid"] = chosen_asset["bundle_uid"]
                slide["image_asset_name"] = chosen_asset["asset_name"]
                slide["image_page"] = chosen_asset.get("page")
                slide["image_relevance"] = "manual"
                slide["image_orientation"] = _image_orientation(chosen_asset)
                slide["image_mode"] = _image_mode_for_slide(slide, chosen_asset, mode_relevance)
                slide["image_choice_mode"] = "manual"
                used_asset_keys.add(_asset_key(chosen_asset))
            else:
                _clear_slide_image(slide)
                slide["image_choice_mode"] = "manual_none"
            continue

        if not chosen_asset or relevance == "none":
            available_assets = [
                asset
                for asset in ordered_assets
                if _asset_key(asset) not in used_asset_keys and _asset_is_usable(asset)
            ]
            candidate_pool = available_assets or ordered_assets

            if source_pages:
                nearby_assets = [
                    asset
                    for asset in candidate_pool
                    if min(abs(int(asset.get("page") or 0) - page) for page in source_pages) <= 1
                ]
                if nearby_assets:
                    candidate_pool = nearby_assets

            ranked_assets = sorted(
                candidate_pool,
                key=lambda asset: _asset_score(
                    asset,
                    source_pages,
                    content_index - ordered_assets.index(asset),
                    slide_keywords,
                ),
            )
            chosen_asset = ranked_assets[0] if ranked_assets else None
            relevance = _relevance_label(chosen_asset, source_pages, slide_keywords) if chosen_asset else "none"

        if relevance == "low" and _should_keep_low_relevance_asset(slide, chosen_asset, source_pages, slide_keywords):
            if int(chosen_asset.get("page") or 0) in source_pages and _asset_quality_bucket(chosen_asset) <= 1:
                relevance = "medium"

        if not chosen_asset or relevance == "none":
            _clear_slide_image(slide)
            slide["image_choice_mode"] = "auto"
            continue

        if source_pages:
            closest_page_distance = min(abs(int(chosen_asset.get("page") or 0) - page) for page in source_pages)
            if closest_page_distance > 1:
                _clear_slide_image(slide)
                slide["image_choice_mode"] = "auto"
                continue

        slide["image_bundle_uid"] = chosen_asset["bundle_uid"]
        slide["image_asset_name"] = chosen_asset["asset_name"]
        slide["image_page"] = chosen_asset.get("page")
        slide["image_relevance"] = relevance
        slide["image_orientation"] = _image_orientation(chosen_asset)
        slide["image_mode"] = _image_mode_for_slide(slide, chosen_asset, relevance)
        slide["image_choice_mode"] = "auto"
        used_asset_keys.add(_asset_key(chosen_asset))

    return slides
