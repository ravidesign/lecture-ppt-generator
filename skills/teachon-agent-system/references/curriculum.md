# Curriculum Agent

## Purpose

The curriculum agent converts selected PDF pages into a teachable lecture structure.

## Main Files

- Persona: `agents/curriculum_designer.py`
- Prompt contract: `tasks/curriculum_tasks.py`
- Crew runner: `crews/lecture_crew.py`
- Stage orchestration and fallback: `flows/lecture_pipeline.py`, `tools/slide_tool.py`

## Responsibilities

- Define learning objectives.
- Identify key concepts and section boundaries.
- Propose a lecture flow that can later become slides.
- Mark which sections are good image candidates.

## Inputs

- page summary
- heading lines discovered from the selected pages
- slide instruction text
- lecture goal

## Expected Output

The result should be a curriculum JSON object that can drive slide drafting.

Typical keys:

- `learning_objectives`
- `structure`
- `key_concepts`
- `difficulty_level`
- optional `page_summary`
- optional `selection_note`

Each structure row should be compatible with downstream slide planning and usually includes:

- `slide_no`
- `type`
- `section_title`
- `title`
- `subtitle`
- `source_pages`
- `image_candidate`
- `content_kind`

## Quality Bar

- Learning objectives should be concrete and teachable.
- Section order should mirror the selected PDF pages, not the whole document.
- Structure should anticipate chapter breaks and dense sections.
- `source_pages` should remain anchored to the chosen range.

## Common Failure Modes

- Producing topic lists that are too broad
- Ignoring section transitions
- Returning objectives that are just headings rewritten
- Missing image-worthy sections

## Safe Ways To Improve It

- Adjust `tasks/curriculum_tasks.py` if the structure is too loose.
- Check `flows/lecture_pipeline.py` fallback behavior when changing required keys.
- If you add fields to `structure`, verify that slide generation and PM summaries do not assume the old shape.

