from __future__ import annotations

from crewai import Agent

import config


def build_curriculum_designer() -> Agent:
    return Agent(
        role="Curriculum Designer",
        goal="PDF 강의 자료를 학습목표, 목차, 주요 섹션 구조로 재설계한다",
        backstory=(
            "당신은 대학 강의 설계자입니다. "
            "자료의 핵심 개념을 구조화하고, 도입-본론-정리 흐름을 만든 뒤 "
            "이미지가 유효한 슬라이드를 구분합니다."
        ),
        tools=[],
        llm=config.make_llm(config.CURRICULUM_MODEL, temperature=0.2, max_tokens=4096),
        allow_delegation=False,
        memory=False,
        max_iter=3,
        verbose=True,
    )
