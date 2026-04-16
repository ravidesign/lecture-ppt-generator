from __future__ import annotations

from copy import deepcopy

from core.pdf_parser import parse_page_range


def _asset_key(asset: dict) -> tuple[str, str]:
    return str(asset.get("bundle_uid") or ""), str(asset.get("asset_name") or "")


def _slide_key(slide: dict) -> tuple[str, str]:
    return str(slide.get("image_bundle_uid") or ""), str(slide.get("image_asset_name") or "")


def _parse_source_pages(source_pages: str, max_page: int) -> list[int]:
    source = str(source_pages or "").strip()
    if not source or max_page < 1:
        return []
    return parse_page_range(source, max_page)


def _asset_score(asset: dict, source_pages: list[int], fallback_index: int) -> tuple[int, int, int]:
    asset_page = int(asset.get("page") or 0)

    if source_pages:
        if asset_page in source_pages:
            distance = 0
        else:
            distance = min(abs(asset_page - page) for page in source_pages)
        return (0 if asset_page in source_pages else 1, distance, fallback_index)

    return (2, abs(fallback_index), asset_page)


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
        available_assets = [asset for asset in ordered_assets if _asset_key(asset) not in used_asset_keys]
        candidate_pool = available_assets or ordered_assets

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

        slide["image_bundle_uid"] = chosen_asset["bundle_uid"]
        slide["image_asset_name"] = chosen_asset["asset_name"]
        slide["image_page"] = chosen_asset.get("page")
        used_asset_keys.add(_asset_key(chosen_asset))

    return slides
