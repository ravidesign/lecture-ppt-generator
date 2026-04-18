from __future__ import annotations

import json
import re
from typing import Any

from crewai import Crew, Process, Task

from runtime import disable_crewai_telemetry


def _extract_raw_output(result: Any) -> str:
    if hasattr(result, "raw") and isinstance(result.raw, str):
        return result.raw.strip()
    text = str(result or "").strip()
    return text


def _load_jsonish(text: str):
    clean = text.replace("```json", "").replace("```", "").strip()
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = clean.find(start_char)
        end = clean.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            candidate = clean[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return json.loads(clean)


def run_single_agent_json(agent, description: str, expected_output: str):
    disable_crewai_telemetry()
    task = Task(description=description, expected_output=expected_output, agent=agent)
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        language="en",
    )
    result = crew.kickoff()
    return _load_jsonish(_extract_raw_output(result))
