# Question Agent

## Purpose

The question agent creates assessment items grounded in the lecture content.

## Main Files

- Persona: `agents/question_designer.py`
- Prompt contract: `tasks/question_tasks.py`
- Crew runner: `crews/exam_crew.py`
- Stage orchestration and fallback: `flows/exam_pipeline.py`, `tools/slide_tool.py`

## Responsibilities

- Generate questions from curriculum, slides, and source excerpt only.
- Respect target question count and difficulty mix.
- Include answers, explanations, and source page references.

## Inputs

- curriculum JSON
- slides JSON
- question count
- difficulty text
- source excerpt

## Expected Output

A JSON object with a `questions` array.

Each question should include:

- `type`
- `difficulty`
- `points`
- `prompt`
- `answer`
- `explanation`
- `source_pages`

Multiple-choice items may also include:

- `choices`

## Quality Bar

- Questions must be derivable from the supplied material.
- Difficulty distribution should follow the requested mix as closely as possible.
- Answers and explanations should be internally consistent.
- Source pages should point back to the lecture material.

## Common Failure Modes

- Questions that rely on outside knowledge
- Repetitive prompts across the set
- Difficulty labels that do not match item complexity
- Missing explanations or weak answer grounding

## Safe Ways To Improve It

- Update `tasks/question_tasks.py` before touching the agent persona for most quality changes.
- If the question object shape changes, update reviewer logic and DOCX generation consumers.
- Keep the question agent focused on generation; post-generation QA belongs to the reviewer.

