from __future__ import annotations

from copy import deepcopy

from core.slide_enricher import attach_pdf_images_to_slides
from core.slide_quality import build_outline, build_quality_summary, review_slides


def _points(slide: dict) -> list[str]:
    return [str(point).strip() for point in (slide.get("points", []) or []) if str(point).strip()]


def _variant_blueprints(slide: dict) -> list[dict]:
    points = _points(slide)
    has_image = bool(slide.get("image_asset_name"))
    orientation = str(slide.get("image_orientation") or "square").lower()
    kind = str(slide.get("content_kind") or "explain").lower()

    if has_image:
        return [
            {
                "id": "image-left-hero",
                "label": "시안 1 · 이미지 좌측 강조",
                "layout": "image_left",
                "image_mode": "hero",
                "point_limit": 4 if kind != "process" else 3,
            },
            {
                "id": "image-top-hero",
                "label": "시안 2 · 이미지 상단 강조",
                "layout": "image_top",
                "image_mode": "hero",
                "point_limit": 4 if orientation != "landscape" else 3,
            },
            {
                "id": "minimal-visual-focus",
                "label": "시안 3 · 텍스트 축약형",
                "layout": "highlight" if kind not in {"compare", "process"} else "classic",
                "image_mode": "hero",
                "point_limit": 3,
            },
        ]

    if kind == "compare":
        return [
            {"id": "compare-balanced", "label": "시안 1 · 비교형", "layout": "compare", "image_mode": "none", "point_limit": 4},
            {"id": "compare-classic", "label": "시안 2 · 설명형", "layout": "classic", "image_mode": "none", "point_limit": 4},
            {"id": "compare-split", "label": "시안 3 · 분할형", "layout": "split", "image_mode": "none", "point_limit": 4},
        ]

    if kind == "process":
        return [
            {"id": "process-steps", "label": "시안 1 · 단계형", "layout": "process", "image_mode": "none", "point_limit": 4},
            {"id": "process-cards", "label": "시안 2 · 카드형", "layout": "card", "image_mode": "none", "point_limit": 4},
            {"id": "process-classic", "label": "시안 3 · 설명형", "layout": "classic", "image_mode": "none", "point_limit": 4},
        ]

    return [
        {"id": "classic-balanced", "label": "시안 1 · 설명형", "layout": "classic", "image_mode": "none", "point_limit": min(max(len(points), 3), 4)},
        {"id": "split-section", "label": "시안 2 · 분할형", "layout": "split", "image_mode": "none", "point_limit": 4},
        {"id": "card-summary", "label": "시안 3 · 카드형", "layout": "card", "image_mode": "none", "point_limit": 5},
    ]


def _apply_variant_blueprint(slide: dict, blueprint: dict) -> dict:
    variant = deepcopy(slide)
    variant["layout"] = blueprint["layout"]
    variant["variant_origin"] = blueprint["id"]
    variant["variant_label"] = blueprint["label"]
    variant["image_mode"] = blueprint["image_mode"]

    if blueprint.get("point_limit"):
        variant["points"] = _points(variant)[: int(blueprint["point_limit"])]

    if variant.get("content_kind") == "process":
        variant["diagram_steps"] = _points(variant)[:4]

    if variant.get("content_kind") == "compare":
        points = _points(variant)
        midpoint = max(1, len(points) // 2)
        variant["compare_left_points"] = points[:midpoint][:3]
        variant["compare_right_points"] = points[midpoint:][:3] or points[:2]

    return variant


def generate_slide_variants(
    slides: list[dict],
    slide_index: int,
    design: dict,
    assets: list[dict] | None,
    selected_pages: list[int] | None = None,
    variant_count: int = 3,
) -> list[dict]:
    if slide_index < 0 or slide_index >= len(slides):
        return []

    source_slide = slides[slide_index]
    if str(source_slide.get("role") or "content").lower() == "chapter":
        return []
    if str(source_slide.get("type", "content")).lower() != "content":
        return []

    variants = []
    for blueprint in _variant_blueprints(source_slide)[: max(1, variant_count)]:
        deck = deepcopy(slides)
        deck[slide_index] = _apply_variant_blueprint(deck[slide_index], blueprint)

        reviewed = review_slides(deck, selected_pages=selected_pages)
        enriched = attach_pdf_images_to_slides(reviewed["slides"], assets)
        final = review_slides(enriched, selected_pages=selected_pages)
        variant_slide = final["slides"][slide_index]
        variant_slide["variant_origin"] = blueprint["id"]
        variant_slide["variant_label"] = blueprint["label"]
        variants.append(
            {
                "id": blueprint["id"],
                "label": blueprint["label"],
                "rationale": variant_slide.get("decision_note", ""),
                "slide": variant_slide,
                "outline": build_outline(final["slides"]),
                "quality": build_quality_summary(final["slides"]),
            }
        )

    return variants
