from __future__ import annotations

from crewai import Agent

import config


def build_question_designer() -> Agent:
    return Agent(
        role="Question Designer",
        goal="강의 내용에 기반한 시험 문제와 정답, 해설을 만든다",
        backstory=(
            "당신은 시험 출제 경험이 풍부한 교육평가 전문가입니다. "
            "원문에 근거한 문항만 출제하고 난이도 분배를 지킵니다."
        ),
        tools=[],
        llm=config.make_llm(config.QUESTION_MODEL, temperature=0.2, max_tokens=8192),
        allow_delegation=False,
        memory=False,
        max_iter=3,
        verbose=True,
    )
