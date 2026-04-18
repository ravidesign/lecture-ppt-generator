from __future__ import annotations

from crewai import Agent

import config


def build_layout_designer() -> Agent:
    return Agent(
        role="Layout Designer",
        goal="슬라이드별 레이아웃과 이미지 사용 정책을 강의 친화적으로 최적화한다",
        backstory=(
            "당신은 발표 자료 디자이너입니다. "
            "텍스트 밀도, 이미지 relevance, 페이지 역할에 맞게 레이아웃을 조정합니다."
        ),
        tools=[],
        llm=config.make_llm(config.LAYOUT_MODEL, temperature=0.2, max_tokens=4096),
        allow_delegation=False,
        memory=False,
        max_iter=2,
        verbose=True,
    )
