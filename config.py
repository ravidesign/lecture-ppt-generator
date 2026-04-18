from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PPTX_DIR = OUTPUTS_DIR / "pptx"
DOCX_DIR = OUTPUTS_DIR / "docx"
LOGS_DIR = OUTPUTS_DIR / "logs"

PM_MODEL = "claude-opus-4-5"
CURRICULUM_MODEL = "claude-sonnet-4-6"
CONTENT_MODEL = "claude-sonnet-4-6"
FACT_CHECKER_MODEL = "claude-sonnet-4-6"
QUESTION_MODEL = "claude-sonnet-4-6"
REVIEWER_MODEL = "claude-sonnet-4-6"
LAYOUT_MODEL = "claude-haiku-4-5"
FORMATTER_MODEL = "claude-haiku-4-5"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()


def ensure_dirs() -> None:
    for path in [OUTPUTS_DIR, PPTX_DIR, DOCX_DIR, LOGS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def normalize_anthropic_model_name(model: str) -> str:
    text = (model or "").strip()
    if text.startswith("anthropic/"):
        return text.split("/", 1)[1]
    return text


def make_llm(model: str, temperature: float = 0.2, max_tokens: int = 4096):
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model_name": normalize_anthropic_model_name(model),
        "temperature": temperature,
        "max_tokens_to_sample": max_tokens,
        "timeout": 120,
        "max_retries": 2,
    }
    if ANTHROPIC_API_KEY:
        kwargs["api_key"] = ANTHROPIC_API_KEY
    return ChatAnthropic(**kwargs)


ensure_dirs()
