# System Map

This reference describes how the Teach-On agent system is wired today and where each contract lives.

## Pipeline Order

The end-to-end lecture and exam flow is defined in `flows/full_pipeline.py`.

Current order:

1. PM kickoff marks the job as coordinated.
2. Curriculum designs the lecture structure.
3. Content and question run in parallel for the first draft.
4. Fact checker validates slide fidelity and can trigger up to 3 content rewrites.
5. Reviewer validates questions and can trigger up to 3 question rewrites.
6. Layout applies slide-level layout and image strategy.
7. PM performs a final review and writes a summary.
8. Formatter is represented in the trace, but final export is handled deterministically in `app.py`.

## Runtime File Map

- `agents/*.py`: CrewAI agent persona, goal, model, and iteration limits.
- `tasks/*.py`: Prompt contract and required output shape for each stage.
- `crews/*.py`: Thin wrappers that run a single agent and parse JSON.
- `flows/*.py`: Orchestration, retries, fallbacks, and stage composition.
- `core/agent_control.py`: Manual agent tasks used by dashboard and chat integrations.
- `app.py`: API layer, Slack command handling, saved payload updates, PPT and DOCX generation.
- `core/dashboard_service.py`: Reads saved outputs and active jobs for the dashboard.

## Saved Payload Contract

Generated outputs are stored in `outputs/<uid>_slides.json`.

Common fields:

- `slides`
- `questions`
- `curriculum`
- `exam_summary`
- `exam_settings`
- `agent_trace`
- `pm_summary`
- `artifacts`
- `page_plan`
- `page_plan_preview`
- `lecture_goal`
- `design`
- `assets`

If you change any of these fields, also inspect:

- `app.py` saved payload load and update paths
- `core/dashboard_service.py`
- preview and editor UIs in `templates/index.html` and `templates/preview.html`

## Slide Contract Highlights

The strongest slide schema guidance currently lives in `core/claude_analyzer.py` and is normalized by `core/slide_quality.py`.

Content slides are expected to carry:

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

Downstream code also cares about:

- `image_bundle_uid`
- `image_asset_name`
- `image_page`
- `image_choice_mode`

## Question Contract Highlights

Question generation and review rely on question objects that include:

- prompt or question text
- answer
- explanation
- difficulty
- source pages
- type

Reviewer output can also include:

- `status`
- `issues`
- `reviewed_questions`
- `shuffle_ready`

## Manual Agent Tasks

Manual agent calls for dashboard and chat integrations use `core/agent_control.py`.

The task system provides:

- `create_agent_task`
- `run_agent_task`
- `run_agent_task_async`
- `list_agent_tasks`
- `get_agent_task`

Important behavior:

- Manual tasks are freeform review and advice, not the same JSON contract as pipeline crews.
- Role-specific notes for manual mode live in `core/agent_control.py`.
- Slack already uses this path in `app.py`; Telegram should reuse the same path.

## Change Checklist

When changing an agent, check all four layers:

1. Persona in `agents/*.py`
2. Prompt contract in `tasks/*.py`
3. Crew wrapper in `crews/*.py`
4. Flow and fallback logic in `flows/*.py`

If output shape changes, also check:

5. Persistence and API readers in `app.py`
6. Dashboard readers in `core/dashboard_service.py`
7. Manual agent task summaries in `core/agent_control.py`

