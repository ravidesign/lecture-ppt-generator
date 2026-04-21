from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config
from core.agent_control import available_agents, create_agent_task, run_agent_task_async
from core.dashboard_service import dashboard_job_detail, dashboard_jobs
from core.slack_service import format_share_message


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _append_pm_event(chat_id: str, role: str, text: str, *, metadata: dict[str, Any] | None = None) -> None:
    data = _read_json(config.PM_THREADS_FILE, {"threads": {}})
    threads = data.get("threads")
    if not isinstance(threads, dict):
        threads = {}

    key = str(chat_id or "unknown").strip() or "unknown"
    thread = threads.get(key) or {"chat_id": key, "events": []}
    events = thread.get("events")
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "time": _iso_now(),
            "role": role,
            "text": str(text or "").strip(),
            "metadata": metadata or {},
        }
    )
    thread["events"] = events[-120:]
    thread["updated_at"] = _iso_now()
    threads[key] = thread
    data["threads"] = threads
    data["updated_at"] = _iso_now()
    _write_json(config.PM_THREADS_FILE, data)


def summarize_jobs(limit: int = 6) -> str:
    outputs, jobs = dashboard_jobs()
    parts: list[str] = []
    if jobs:
        parts.append("최근 분석 작업")
        for item in jobs[:limit]:
            parts.append(
                f"• {item.get('job_id')} · {item.get('status')} · {item.get('stage') or 'stage 없음'}"
            )
    if outputs:
        if parts:
            parts.append("")
        parts.append("최근 생성 결과")
        for item in outputs[:limit]:
            parts.append(
                f"• {item.get('uid')} · {item.get('pdf_name') or item.get('download_name')} · "
                f"{item.get('slide_count', 0)}장 / {item.get('question_count', 0)}문항"
            )
    return "\n".join(parts) if parts else "현재 표시할 Teach-On 작업이 없습니다."


def summarize_job_detail(target_ref: str) -> str:
    detail = dashboard_job_detail(target_ref)
    if not detail:
        return "작업을 찾을 수 없습니다. uid 또는 job id를 다시 확인해 주세요."

    if "slides" in detail:
        lines = [
            f"결과물: {detail.get('pdf_name') or detail.get('download_name') or target_ref}",
            f"슬라이드 {len(detail.get('slides') or [])}장 · 문항 {len(detail.get('questions') or [])}개",
        ]
        preview_url = detail.get("preview_url") or ""
        if preview_url and config.PUBLIC_BASE_URL:
            lines.append(f"미리보기: {config.PUBLIC_BASE_URL.rstrip('/')}{preview_url}")
        return "\n".join(lines)

    return (
        f"분석 Job {detail.get('job_id')}\n"
        f"상태: {detail.get('status')}\n"
        f"단계: {detail.get('stage')}\n"
        f"메시지: {detail.get('message') or '없음'}"
    )


def format_agent_task_result(task: dict[str, Any]) -> str:
    target_ref = task.get("target_ref") or "대상 없음"
    return (
        f"{task.get('agent_label')} 작업 결과\n"
        f"대상: {target_ref}\n"
        f"상태: {task.get('status')}\n\n"
        f"{task.get('result_preview') or task.get('message') or ''}"
    ).strip()


def help_text() -> str:
    lines = [
        "Teach-On Telegram PM 명령",
        "• /start 또는 /help : 도움말",
        "• /jobs : 최근 생성 결과 / 분석 작업 보기",
        "• /status <uid-or-job> : 특정 작업 상세 보기",
        "• /share <uid> : 결과물 링크 요약 보기",
        "• /feedback <uid> <message> : PM에게 피드백 전달",
        "• /pm <message> : PM에게 직접 지시",
        "• /work <message> : PM에게 다음 액션/실행 계획 요청",
    ]
    if config.TELEGRAM_PM_ONLY_MODE:
        lines.append("• 일반 메시지도 PM inbox로 바로 전달됩니다.")
    else:
        lines.append("• /task <agent> <uid> <instruction> : 특정 에이전트에 작업 지시")
        lines.append(
            "  지원 agent: " + ", ".join(item["key"] for item in available_agents())
        )
    return "\n".join(lines)


def _queue_agent_task(
    *,
    agent: str,
    target_ref: str,
    instruction: str,
    chat_id: str,
    message_id: int | None,
    requested_by: str,
    on_complete: Callable[[dict], None] | None,
) -> dict:
    task = create_agent_task(
        {
            "agent": agent,
            "target_ref": target_ref,
            "instruction": instruction,
            "requested_by": requested_by,
            "source": "telegram",
            "transport": "telegram",
            "transport_chat_id": chat_id,
            "transport_message_id": str(message_id or "").strip(),
        }
    )
    _append_pm_event(
        chat_id,
        "system",
        f"{agent} 작업 접수",
        metadata={
            "task_id": task.get("id"),
            "target_ref": target_ref,
            "message_id": message_id,
        },
    )
    run_agent_task_async(task["id"], on_complete=on_complete)
    return task


def _split_command(raw: str) -> tuple[str, list[str], str]:
    parts = str(raw or "").strip().split()
    if not parts:
        return "", [], ""
    command = parts[0].split("@", 1)[0].lower()
    args = parts[1:]
    rest = str(raw or "").strip()[len(parts[0]) :].strip()
    return command, args, rest


def _pm_ack(task: dict[str, Any]) -> str:
    return f"PM에게 전달했습니다. task_id={task['id']}"


def _dispatch_pm_request(
    instruction: str,
    *,
    target_ref: str,
    chat_id: str,
    message_id: int | None,
    requested_by: str,
    on_complete: Callable[[dict], None] | None,
) -> dict:
    if not config.PM_DISPATCH_ENABLED:
        return {
            "reply_text": (
                "PM dispatcher가 아직 비활성화되어 있습니다.\n"
                "`.env`에서 `PM_DISPATCH_ENABLED=true` 로 켜면 PM inbox가 실제로 동작합니다."
            )
        }
    task = _queue_agent_task(
        agent="pm",
        target_ref=target_ref,
        instruction=instruction,
        chat_id=chat_id,
        message_id=message_id,
        requested_by=requested_by,
        on_complete=on_complete,
    )
    return {"reply_text": _pm_ack(task), "task": task}


def handle_telegram_message(
    text: str,
    *,
    chat_id: str,
    message_id: int | None = None,
    username: str = "",
    display_name: str = "",
    on_complete: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    raw = str(text or "").strip()
    requested_by = f"telegram:{username or display_name or chat_id}"
    _append_pm_event(
        chat_id,
        "user",
        raw,
        metadata={
            "message_id": message_id,
            "requested_by": requested_by,
        },
    )

    if not raw:
        return {"reply_text": help_text()}

    command, args, rest = _split_command(raw)

    if command in {"/start", "/help"}:
        return {"reply_text": help_text()}
    if command == "/jobs":
        return {"reply_text": summarize_jobs()}
    if command == "/status":
        if not args:
            return {"reply_text": "예: /status <uid-or-job>"}
        return {"reply_text": summarize_job_detail(args[0])}
    if command == "/share":
        if not args:
            return {"reply_text": "예: /share <uid>"}
        detail = dashboard_job_detail(args[0])
        if not detail or "slides" not in detail:
            return {"reply_text": "공유할 결과물을 찾지 못했습니다."}
        return {"reply_text": format_share_message(detail, args[0])}
    if command == "/feedback":
        if len(args) < 2:
            return {"reply_text": "예: /feedback <uid> <message>"}
        feedback_message = " ".join(args[1:]).strip()
        return _dispatch_pm_request(
            f"사용자 피드백을 기록하고 다음 액션을 제안하세요: {feedback_message}",
            target_ref=args[0],
            chat_id=chat_id,
            message_id=message_id,
            requested_by=requested_by,
            on_complete=on_complete,
        )
    if command == "/task":
        if config.TELEGRAM_PM_ONLY_MODE:
            return {"reply_text": "현재 Telegram은 PM 전용입니다. `/pm ...` 또는 일반 메시지로 요청해 주세요."}
        if len(args) < 3:
            return {"reply_text": "예: /task <agent> <uid> <instruction>"}
        agent = args[0].strip().lower()
        supported_agents = {item["key"] for item in available_agents()}
        if agent not in supported_agents:
            return {"reply_text": "지원하지 않는 에이전트입니다."}
        task = _queue_agent_task(
            agent=agent,
            target_ref=args[1].strip(),
            instruction=" ".join(args[2:]).strip(),
            chat_id=chat_id,
            message_id=message_id,
            requested_by=requested_by,
            on_complete=on_complete,
        )
        return {"reply_text": f"{task['agent_label']} 작업을 접수했습니다. task_id={task['id']}", "task": task}
    if command in {"/pm", "/work"}:
        if not rest:
            return {"reply_text": f"예: {command} Telegram PM webhook 구현 계획 세워줘"}
        return _dispatch_pm_request(
            rest,
            target_ref="",
            chat_id=chat_id,
            message_id=message_id,
            requested_by=requested_by,
            on_complete=on_complete,
        )
    if command.startswith("/"):
        return {"reply_text": help_text()}
    if config.TELEGRAM_PM_ONLY_MODE:
        return _dispatch_pm_request(
            raw,
            target_ref="",
            chat_id=chat_id,
            message_id=message_id,
            requested_by=requested_by,
            on_complete=on_complete,
        )
    return {"reply_text": help_text()}
