# PM Agent

## Purpose

The PM agent is the system-level coordinator and final reviewer.

It has two modes:

- Pipeline final review mode
- Manual dashboard or chat task mode

## Main Files

- Persona: `agents/orchestrator.py`
- Final review prompt: `tasks/orchestrator_tasks.py`
- Final review crew runner: `crews/full_crew.py`
- Manual task execution: `core/agent_control.py`

## Responsibilities

- Summarize whether the full lecture and exam draft is ready.
- Surface the highest-risk issues at the end of the pipeline.
- In manual mode, triage user feedback and propose next actions.
- Coordinate the system conceptually, even when stage sequencing is implemented in `flows/full_pipeline.py`.

## Inputs

Pipeline final review mode:

- `curriculum_json`
- `slides_json`
- optional `questions_json`

Manual task mode:

- `target_ref`
- freeform `instruction`
- saved output detail from `core/dashboard_service.dashboard_job_detail`

## Expected Outputs

Pipeline mode returns a JSON object with:

- `summary`
- `risks`
- `status`

Manual mode returns a short structured narrative covering:

1. 핵심 판단
2. 바로 실행할 액션
3. 주의할 리스크
4. 필요하면 예시 문안

## Quality Bar

- Must be decisive, not vague.
- Must point to the next action instead of restating data.
- Should mention blockers separately from polish issues.
- Should consider both slides and questions when both exist.

## Common Failure Modes

- Repeating the deck contents without making a decision
- Ignoring question quality when exam generation is enabled
- Producing generic “looks good” summaries
- Failing to convert user feedback into concrete next steps

## Safe Ways To Improve It

- Tighten `tasks/orchestrator_tasks.py` if the final summary needs more structure.
- Adjust role notes in `core/agent_control.py` for better manual task responses.
- Do not assume PM owns retries; retries are owned by `flows/full_pipeline.py`.

