from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
UPLOADS_DIR = Path(os.getenv("UPLOAD_DIR", "uploads") or "uploads")
if not UPLOADS_DIR.is_absolute():
    UPLOADS_DIR = PROJECT_ROOT / UPLOADS_DIR

OUTPUTS_DIR = Path(os.getenv("OUTPUT_DIR", "outputs") or "outputs")
if not OUTPUTS_DIR.is_absolute():
    OUTPUTS_DIR = PROJECT_ROOT / OUTPUTS_DIR

ANALYZE_JOBS_DIR = OUTPUTS_DIR / "analyze_jobs"
PPTX_DIR = OUTPUTS_DIR / "pptx"
DOCX_DIR = OUTPUTS_DIR / "docx"
LOGS_DIR = OUTPUTS_DIR / "logs"
DASHBOARD_DIR = OUTPUTS_DIR / "dashboard"
INTEGRATIONS_FILE = DASHBOARD_DIR / "connectors.json"
AGENT_TASKS_FILE = DASHBOARD_DIR / "agent_tasks.json"
SLACK_ACTIVITY_FILE = DASHBOARD_DIR / "slack_activity.json"

MAX_UPLOAD_MB = max(4, int(os.getenv("MAX_UPLOAD_MB", "24") or "24"))
ADMIN_TOKEN = (
    os.getenv("TEACHON_ADMIN_TOKEN", "").strip()
    or os.getenv("DASHBOARD_ADMIN_TOKEN", "").strip()
)
SESSION_SECRET = (
    os.getenv("TEACHON_SESSION_SECRET", "").strip()
    or os.getenv("FLASK_SECRET_KEY", "").strip()
    or ADMIN_TOKEN
    or "teachon-dev-session-secret"
)
ADMIN_USERNAME = os.getenv("TEACHON_ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("TEACHON_ADMIN_PASSWORD", "").strip()
ADMIN_PASSWORD_HASH = os.getenv("TEACHON_ADMIN_PASSWORD_HASH", "").strip()
DASHBOARD_IP_ALLOWLIST = os.getenv("TEACHON_DASHBOARD_IP_ALLOWLIST", "").strip()
PUBLIC_BASE_URL = (
    os.getenv("TEACHON_PUBLIC_BASE_URL", "").strip()
    or os.getenv("PUBLIC_BASE_URL", "").strip()
)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "").strip()
SLACK_DEFAULT_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "").strip()
SLACK_COMMAND_NAME = os.getenv("SLACK_COMMAND_NAME", "/teachon").strip() or "/teachon"
SLACK_EVENTS_ENABLED = (os.getenv("SLACK_EVENTS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"})
SLACK_REQUEST_TOLERANCE_SECONDS = max(60, int(os.getenv("SLACK_REQUEST_TOLERANCE_SECONDS", "300") or "300"))

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
    for path in [UPLOADS_DIR, OUTPUTS_DIR, ANALYZE_JOBS_DIR, PPTX_DIR, DOCX_DIR, LOGS_DIR, DASHBOARD_DIR]:
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
