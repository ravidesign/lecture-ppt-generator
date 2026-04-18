from __future__ import annotations

from crewai import Agent

import config


def build_fact_checker() -> Agent:
    return Agent(
        role="Fact Checker",
        goal="슬라이드 초안이 원문과 일치하는지 검증하고 수정 지시를 작성한다",
        backstory=(
            "당신은 교육자료 검수자입니다. "
            "누락, 오탈자, 수치 오류, 원문 밖 내용 추가를 엄격하게 잡아냅니다."
        ),
        tools=[],
        llm=config.make_llm(config.FACT_CHECKER_MODEL, temperature=0.1, max_tokens=4096),
        allow_delegation=False,
        memory=False,
        max_iter=3,
        verbose=True,
    )
