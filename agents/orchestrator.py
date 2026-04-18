from __future__ import annotations

from crewai import Agent

import config


def build_orchestrator() -> Agent:
    return Agent(
        role="Teach-On PM Orchestrator",
        goal="강의안과 시험지 생성 전 과정을 조율하고 최종 품질을 판단한다",
        backstory=(
            "당신은 교육 콘텐츠 제작 PM입니다. "
            "각 단계 산출물을 점검하고, 검증 실패 시 재작업을 명확하게 지시합니다."
        ),
        tools=[],
        llm=config.make_llm(config.PM_MODEL, temperature=0.1, max_tokens=2048),
        allow_delegation=False,
        memory=False,
        max_iter=2,
        verbose=True,
    )
