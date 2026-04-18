from __future__ import annotations

from crewai import Agent

import config


def build_content_writer() -> Agent:
    return Agent(
        role="Content Writer",
        goal="원문 기반으로 슬라이드 본문과 발표자 노트를 정확하게 작성한다",
        backstory=(
            "당신은 교육용 슬라이드 전문 작가입니다. "
            "원문 언어를 보존하고, 내용을 빠뜨리지 않으면서 강의 친화적으로 정리합니다."
        ),
        tools=[],
        llm=config.make_llm(config.CONTENT_MODEL, temperature=0.15, max_tokens=8192),
        allow_delegation=False,
        memory=False,
        max_iter=3,
        verbose=True,
    )
