---
name: teachon-agent-system
description: Use when working on Teach-On's multi-agent lecture and exam pipeline, prompt contracts, agent routing, dashboard or chat integrations, or when updating the PM, curriculum, content, fact_checker, question, reviewer, layout, or formatter agent behaviors. Covers stage order, JSON output contracts, retry loops, saved payload structure, and which reference file to load for each agent.
---

# Teach-On Agent System

Use this skill when changing how Teach-On agents think, what they return, how they are orchestrated, or how external channels call them.

## Start Here

1. Read `references/system-map.md` first.
2. Load only the reference file for the agent you are changing.
3. Inspect the matching runtime files:
   - Persona: `agents/*.py`
   - Prompt contract: `tasks/*.py`
   - Crew runner: `crews/*.py`
   - Stage flow and fallback logic: `flows/*.py`
   - Manual agent task execution and chat integrations: `core/agent_control.py`, `app.py`

## Non-Negotiables

- The selected PDF pages are the source of truth.
- Do not change JSON output shapes for one stage unless all consumers are updated.
- Prefer tightening task prompts and validation rules before inflating agent backstories.
- Keep fact-checking stricter than content generation.
- Reuse existing saved payloads and slide update endpoints for feedback loops instead of creating parallel state.
- For dashboard, Slack, or future Telegram integrations, route manual agent work through `core/agent_control.py`.

## Load Guide

- PM orchestration and manual feedback triage: `references/pm.md`
- Curriculum design: `references/curriculum.md`
- Slide drafting: `references/content.md`
- Source fidelity review: `references/fact_checker.md`
- Question generation: `references/question.md`
- Question QA and shuffle readiness: `references/reviewer.md`
- Layout and image policy: `references/layout.md`
- Export checklist and formatter role: `references/formatter.md`

## Common Work Patterns

### Tune one agent

1. Read the agent reference file.
2. Update the prompt contract in `tasks/*.py` first if the output contract or quality bar changes.
3. Update the agent persona in `agents/*.py` only if the role itself changes.
4. Check `flows/*.py` or `crews/*.py` for retries, fallbacks, and downstream assumptions.

### Add a new feedback loop

1. Read `references/system-map.md` and the target agent reference.
2. Reuse saved payloads in `outputs/<uid>_slides.json`.
3. Prefer existing update paths in `app.py` such as slide update, variant generation, and variant apply endpoints.
4. If the loop is user-facing through chat, keep chat parsing separate from agent execution.

### Change saved payload or trace semantics

1. Read `references/system-map.md`.
2. Update producers in `flows/full_pipeline.py` or `app.py`.
3. Update readers in `core/dashboard_service.py`, preview APIs, and any chat share or status paths.

