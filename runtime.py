from __future__ import annotations

import warnings

_PATCHED = False


class _NullTelemetry:
    def __init__(self):
        self.ready = False

    def set_tracer(self):
        return None

    def crew_creation(self, crew):
        return None

    def tool_repeated_usage(self, llm, tool_name: str, attempts: int):
        return None

    def tool_usage(self, llm, tool_name: str, attempts: int):
        return None

    def tool_usage_error(self, llm):
        return None

    def crew_execution_span(self, crew):
        return None

    def end_crew(self, crew, output):
        return None


def disable_crewai_telemetry() -> None:
    global _PATCHED
    if _PATCHED:
        return

    warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*")
    warnings.filterwarnings("ignore", message="Mixing V1 models and V2 models.*")

    try:
        import crewai.agents.executor as executor_module
        import crewai.crew as crew_module
        import crewai.telemtry.telemetry as telemetry_module
        import crewai.tools.tool_usage as tool_usage_module
    except Exception:
        return

    telemetry_module.Telemetry = _NullTelemetry
    crew_module.Telemetry = _NullTelemetry
    tool_usage_module.Telemetry = _NullTelemetry
    executor_module.CrewAgentExecutor._should_force_answer = lambda self: False
    _PATCHED = True
