# Layout Agent

## Purpose

The layout agent recommends slide-level layout and image usage overrides after content exists.

## Main Files

- Persona: `agents/layout_designer.py`
- Prompt contract: `tasks/layout_tasks.py`
- Crew runner: `crews/lecture_crew.py`
- Stage orchestration: `flows/lecture_pipeline.py`
- Layout application and image attachment: `tools/slide_tool.py`, `core/slide_enricher.py`, `core/slide_quality.py`

## Responsibilities

- Recommend better layouts for each slide role and content type.
- Decide when images should be visually dominant versus supporting.
- Improve lecture readability without changing the meaning of the content.

## Inputs

- slides JSON
- extracted image asset summary

## Expected Output

A JSON object with `slide_overrides`.

Each override may include:

- `slide_index`
- `layout`
- `image_mode`
- `note`

## Quality Bar

- Must respect slide role such as chapter versus content.
- Should use image-led layouts only when the chosen asset is relevant and strong enough.
- Should reduce density problems rather than making them worse.
- Must stay compatible with the layout options supported by PPT generation.

## Common Failure Modes

- Overusing hero images
- Assigning layouts unsupported by downstream code
- Ignoring content kind such as process or compare
- Making aesthetic changes that harm teaching clarity

## Safe Ways To Improve It

- Cross-check any new layout vocabulary against `core/slide_quality.py` and `core/ppt_generator.py`.
- If image policy changes, inspect `core/slide_enricher.py`.
- Layout agent should recommend overrides; it should not own persistence logic.

