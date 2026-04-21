# Formatter Agent

## Purpose

The formatter role represents export readiness and artifact planning.

Today, the actual file generation is deterministic and handled in `app.py`, not by a CrewAI formatter stage.

## Main Files

- Persona: `agents/formatter.py`
- Prompt contract: `tasks/formatter_tasks.py`
- Trace handling and export paths: `flows/full_pipeline.py`, `app.py`

## Responsibilities

- In manual or future assisted mode, review whether the draft is ready to export.
- Suggest which artifacts should be generated.
- Protect final output integrity.

## Inputs

- slides JSON
- questions JSON
- exam settings JSON

## Expected Output

If used as an LLM stage, it should return a JSON object with:

- `format_status`
- `artifact_plan`
- `notes`

`artifact_plan` is expected to list any of:

- `ppt`
- `exam`
- `answer`
- `exam_a`
- `exam_b`

## Quality Bar

- Artifact planning should match the current exam settings.
- Notes should focus on export blockers or file completeness.
- The role should remain deterministic-friendly and avoid broad content critique.

## Current Runtime Reality

- `flows/full_pipeline.py` marks formatter as pending in the trace.
- `app.py` performs actual PPT and DOCX export and then marks formatter as completed in the saved trace.
- Manual agent tasks can still call the formatter model through `core/agent_control.py`.

## Common Failure Modes

- Treating formatter like another content generator
- Drifting into PM-style overall review
- Suggesting artifact types unsupported by the current app

## Safe Ways To Improve It

- Keep export semantics aligned with `app.py`.
- If formatter becomes a real pipeline LLM stage later, update the trace rules and saved payload expectations together.
