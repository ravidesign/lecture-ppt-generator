# Content Agent

## Purpose

The content agent turns curriculum structure into lecture-ready slide drafts.

## Main Files

- Persona: `agents/content_writer.py`
- Prompt contract: `tasks/content_tasks.py`
- Slide planner and schema rules: `core/claude_analyzer.py`
- Stage orchestration: `flows/lecture_pipeline.py`
- Normalization and splitting: `core/slide_quality.py`

## Responsibilities

- Draft the slide array in the source document language.
- Keep each slide teachable and not overly dense.
- Write presenter notes for each content slide.
- Respect curriculum intent and revision requests from the fact checker.

## Inputs

- curriculum JSON
- optional revision request
- selected PDF page context from the upstream pipeline

## Expected Output

The output must be a slide JSON array.

Important content slide fields:

- `type`
- `role`
- `section_title`
- `title`
- `subtitle`
- `layout`
- `content_kind`
- `image_mode`
- `source_pages`
- `points`
- `notes`

Downstream normalization may also infer or repair:

- chapter slides
- missing source pages
- missing notes
- layout or content kind mismatches

## Quality Bar

- Exactly one title, one agenda, and one summary slide in the raw draft schema used by `core/claude_analyzer.py`.
- Content slides should usually have 3 to 5 short points.
- Notes should be short but useful for delivery.
- `source_pages` should stay within the selected range.
- Do not invent facts outside the source pages.

## Common Failure Modes

- Dense bullets that later trigger forced splitting
- Missing or weak presenter notes
- Poor `section_title` consistency
- Overusing image-led layouts without evidence
- Returning output that is not valid JSON

## Safe Ways To Improve It

- Tighten `tasks/content_tasks.py` for local behavior changes.
- Update `core/claude_analyzer.py` only when the schema or global generation rules truly change.
- After any schema change, verify `core/slide_quality.py`, `core/slide_enricher.py`, preview UIs, and PPT generation.

