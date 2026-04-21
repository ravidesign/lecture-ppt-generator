# Fact Checker Agent

## Purpose

The fact checker protects source fidelity for slide drafts.

## Main Files

- Persona: `agents/fact_checker.py`
- Prompt contract: `tasks/factcheck_tasks.py`
- Crew runner: `crews/lecture_crew.py`
- Stage orchestration and retry loop: `flows/lecture_pipeline.py`, `flows/full_pipeline.py`
- Fallback heuristic: `tools/slide_tool.py`

## Responsibilities

- Compare slide drafts against the source excerpt.
- Decide `PASS`, `REVISE`, or `REJECT`.
- Explain what is wrong and provide a revision request suitable for the content agent.

## Inputs

- curriculum JSON
- slides JSON
- source excerpt from selected PDF pages

## Expected Output

A JSON object with:

- `status`
- `issues`
- `revision_request`

## Quality Bar

- Must be strict about hallucinations, omitted facts, and numeric mistakes.
- `revision_request` should be reusable as an instruction for the content rewrite.
- Should distinguish fixable issues from fatal fidelity failure.

## Common Failure Modes

- Saying `REVISE` without actionable correction text
- Catching style issues but missing source violations
- Passing slides that drift outside selected pages
- Rejecting without explaining the concrete mismatch

## Safe Ways To Improve It

- Keep this agent stricter than content and question generation.
- When changing `status` semantics, update `flows/full_pipeline.py`.
- Do not collapse `REVISE` and `REJECT`; the retry loop depends on that distinction.

