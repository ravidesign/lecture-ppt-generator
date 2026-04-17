from __future__ import annotations

import re
from copy import deepcopy

from core.pdf_parser import parse_page_range


PAGE_NUMBER_RE = re.compile(r"\d+")


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
    if coverage >= 0.04 or display_area >= 48000:
        return 1
    if coverage >= 0.02 or display_area >= 24000:
        return 2
    return 3


def _asset_is_usable(asset: dict) -> bool:
    return _asset_quality_bucket(asset) <= 2


def _asset_score(asset: dict, source_pages: list[int], fallback_index: int) -> tuple[int, int, int]:
    asset_page = int(asset.get("page") or 0)
    quality_bucket = _asset_quality_bucket(asset)

    if source_pages:
        if asset_page in source_pages:
            distance = 0
        else:
            distance = min(abs(asset_page - page) for page in source_pages)
        return (0 if asset_page in source_pages else 1, distance, quality_bucket, fallback_index)

    return (2, quality_bucket, abs(fallback_index), asset_page)


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

        current_key = _slide_key(slide)
        if current_key in assets_by_key:
            continue

        source_pages = _parse_source_pages(slide.get("source_pages", ""), max_page)
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
                if min(abs(int(asset.get("page") or 0) - page) for page in source_pages) <= 2
            ]
            if nearby_assets:
                candidate_pool = nearby_assets

        ranked_assets = sorted(
            candidate_pool,
            key=lambda asset: _asset_score(
                asset,
                source_pages,
                content_index - ordered_assets.index(asset),
            ),
        )
        chosen_asset = ranked_assets[0] if ranked_assets else None
        if not chosen_asset:
            continue

        if source_pages:
            closest_page_distance = min(abs(int(chosen_asset.get("page") or 0) - page) for page in source_pages)
            if closest_page_distance > 3:
                continue
        elif _asset_quality_bucket(chosen_asset) >= 2:
            continue

        slide["image_bundle_uid"] = chosen_asset["bundle_uid"]
        slide["image_asset_name"] = chosen_asset["asset_name"]
        slide["image_page"] = chosen_asset.get("page")
        used_asset_keys.add(_asset_key(chosen_asset))

    return slides
