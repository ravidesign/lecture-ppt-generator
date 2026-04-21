# Reviewer Agent

## Purpose

The reviewer agent performs QA on the generated question set.

## Main Files

- Persona: `agents/reviewer.py`
- Prompt contract: `tasks/review_tasks.py`
- Crew runner: `crews/exam_crew.py`
- Retry loop: `flows/exam_pipeline.py`, `flows/full_pipeline.py`
- Fallback heuristic: `tools/slide_tool.py`

## Responsibilities

- Detect duplicate or weak questions.
- Validate answer structure and multi-select correctness.
- Judge whether the question set is ready for shuffling or needs regeneration.

## Inputs

- questions JSON
- slides JSON

## Expected Output

A JSON object containing:

- `status`
- `issues`
- `reviewed_questions`
- `shuffle_ready`

## Quality Bar

- Must catch repeated prompts and answer-key problems.
- Should preserve usable questions rather than needlessly discarding the whole set.
- Should produce feedback specific enough for regeneration.

## Common Failure Modes

- Treating all issues as fatal
- Returning the original questions unchanged when defects exist
- Missing ambiguous wording or duplicate concepts
- Ignoring mismatch between lecture slides and question wording

## Safe Ways To Improve It

- Keep retry semantics compatible with `flows/full_pipeline.py`.
- If `reviewed_questions` shape changes, inspect exam export and preview consumers.
- Reviewer should be narrower than PM: question QA only, not whole-deck commentary.

