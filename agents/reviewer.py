from __future__ import annotations

from crewai import Agent

import config


def build_reviewer() -> Agent:
    return Agent(
        role="Reviewer",
        goal="문항 중복, 난이도, 정답 수, 강의 내용 일치를 검토한다",
        backstory=(
            "당신은 시험지 편집장입니다. "
            "문항 품질을 높이고 A/B 셔플 버전까지 준비합니다."
        ),
        tools=[],
        llm=config.make_llm(config.REVIEWER_MODEL, temperature=0.1, max_tokens=4096),
        allow_delegation=False,
        memory=False,
        max_iter=3,
        verbose=True,
    )
