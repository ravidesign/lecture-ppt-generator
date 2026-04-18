from __future__ import annotations

from crewai import Agent

import config


def build_formatter() -> Agent:
    return Agent(
        role="Formatter",
        goal="최종 PPT와 DOCX 산출물을 안정적으로 생성한다",
        backstory=(
            "당신은 문서 포매팅 엔지니어입니다. "
            "레이아웃과 문제 구조를 깨지 않게 파일로 변환합니다."
        ),
        tools=[],
        llm=config.make_llm(config.FORMATTER_MODEL, temperature=0.0, max_tokens=2048),
        allow_delegation=False,
        memory=False,
        max_iter=1,
        verbose=True,
    )
