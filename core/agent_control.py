from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config
from core.dashboard_service import dashboard_job_detail


AGENT_OPTIONS = {
    "pm": {"label": "PM Orchestrator", "model": config.PM_MODEL},
    "curriculum": {"label": "Curriculum Designer", "model": config.CURRICULUM_MODEL},
    "content": {"label": "Content Writer", "model": config.CONTENT_MODEL},
    "fact_checker": {"label": "Fact Checker", "model": config.FACT_CHECKER_MODEL},
    "question": {"label": "Question Designer", "model": config.QUESTION_MODEL},
    "reviewer": {"label": "Reviewer", "model": config.REVIEWER_MODEL},
    "layout": {"label": "Layout Designer", "model": config.LAYOUT_MODEL},
    "formatter": {"label": "Formatter", "model": config.FORMATTER_MODEL},
}

_TASK_LOCK = threading.Lock()


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


def _task_store() -> dict:
    data = _read_json(config.AGENT_TASKS_FILE, {"tasks": []})
    if not isinstance(data, dict):
        return {"tasks": []}
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        data["tasks"] = []
    return data


def available_agents() -> list[dict[str, str]]:
    return [{"key": key, "label": meta["label"]} for key, meta in AGENT_OPTIONS.items()]


def list_agent_tasks(limit: int = 30) -> list[dict]:
    tasks = [task for task in _task_store().get("tasks", []) if isinstance(task, dict)]
    tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return tasks[: max(1, min(100, int(limit or 30)))]


def get_agent_task(task_id: str) -> dict | None:
    for task in _task_store().get("tasks", []):
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    return None


def _upsert_task(updated_task: dict) -> dict:
    with _TASK_LOCK:
        data = _task_store()
        tasks = [task for task in data.get("tasks", []) if isinstance(task, dict)]
        replaced = False
        for index, task in enumerate(tasks):
            if task.get("id") != updated_task.get("id"):
                continue
            tasks[index] = updated_task
            replaced = True
            break
        if not replaced:
            tasks.append(updated_task)
        data["tasks"] = tasks
        data["updated_at"] = _iso_now()
        _write_json(config.AGENT_TASKS_FILE, data)
    return updated_task


def _normalize_task_payload(data: dict) -> dict:
    agent = str(data.get("agent") or "pm").strip().lower()
    if agent not in AGENT_OPTIONS:
        raise ValueError("지원하지 않는 에이전트입니다.")

    instruction = str(data.get("instruction") or "").strip()
    if not instruction:
        raise ValueError("에이전트에게 전달할 지시사항을 입력해 주세요.")

    requested_by = str(data.get("requested_by") or "").strip()
    source = str(data.get("source") or "dashboard").strip().lower() or "dashboard"
    target_ref = str(data.get("target_ref") or "").strip()

    now = _iso_now()
    return {
        "id": uuid.uuid4().hex[:10],
        "agent": agent,
        "agent_label": AGENT_OPTIONS[agent]["label"],
        "instruction": instruction,
        "target_ref": target_ref,
        "source": source,
        "requested_by": requested_by,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "result": "",
        "result_preview": "",
        "message": "작업 대기 중입니다.",
        "channel_id": str(data.get("channel_id") or "").strip(),
        "thread_ts": str(data.get("thread_ts") or "").strip(),
        "response_url": str(data.get("response_url") or "").strip(),
        "transport": str(data.get("transport") or "").strip().lower(),
        "transport_chat_id": str(data.get("transport_chat_id") or "").strip(),
        "transport_message_id": str(data.get("transport_message_id") or "").strip(),
        "parent_task_id": str(data.get("parent_task_id") or "").strip(),
        "delegated_by": str(data.get("delegated_by") or "").strip(),
    }


def create_agent_task(data: dict) -> dict:
    task = _normalize_task_payload(data)
    return _upsert_task(task)


def _detail_context(target_ref: str) -> dict | None:
    if not target_ref:
        return None
    return dashboard_job_detail(target_ref)


def _slide_lines(detail: dict | None, limit: int = 10) -> list[str]:
    if not detail:
        return []
    slides = detail.get("slides") or []
    lines: list[str] = []
    for index, slide in enumerate(slides[:limit], start=1):
        title = str(slide.get("title") or slide.get("subtitle") or f"Slide {index}").strip()
        points = slide.get("points") or slide.get("bullets") or []
        if not isinstance(points, list):
            points = [points]
        point_text = " / ".join(str(item).strip() for item in points[:3] if str(item).strip())
        lines.append(f"{index}. {title}" + (f" — {point_text}" if point_text else ""))
    return lines


def _question_lines(detail: dict | None, limit: int = 5) -> list[str]:
    if not detail:
        return []
    questions = detail.get("questions") or []
    lines: list[str] = []
    for index, question in enumerate(questions[:limit], start=1):
        prompt = str(question.get("question") or question.get("prompt") or f"문항 {index}").strip()
        answer = question.get("answer") or question.get("correct_answer") or ""
        lines.append(f"{index}. {prompt}" + (f" | 정답: {answer}" if answer else ""))
    return lines


def _build_agent_prompt(task: dict, detail: dict | None) -> str:
    target_ref = task.get("target_ref") or "target 없음"
    lecture_goal = detail.get("lecture_goal") if detail else ""
    exam_summary = detail.get("exam_summary") if detail else None
    curriculum = detail.get("curriculum") if detail else None
    slide_lines = _slide_lines(detail)
    question_lines = _question_lines(detail)

    role_notes = {
        "pm": "전체 작업을 보고 우선순위와 다음 액션을 정리하세요.",
        "curriculum": "강의 구조, 챕터 흐름, 학습목표 관점에서 개선안을 제시하세요.",
        "content": "슬라이드 내용과 발표 흐름을 더 명확하게 다듬는 방향으로 제안하세요.",
        "fact_checker": "사실 검증 관점에서 의심 지점, 근거 보강 포인트, 재확인 체크리스트를 제시하세요.",
        "question": "강의 내용을 바탕으로 추가 평가 문항 또는 문항 개선안을 제시하세요.",
        "reviewer": "강의안/문항 품질 리뷰어로서 가독성, 중복, 난이도, 설계 오류를 짚으세요.",
        "layout": "이미지 활용, 레이아웃 밀도, 분할 적절성, 강의 현장 가독성 관점에서 개선안을 제시하세요.",
        "formatter": "산출물 완성도와 전달력 측면에서 export 전 체크리스트를 정리하세요.",
    }

    return (
        "당신은 Teach-On 운영 대시보드에서 수동 호출된 AI 에이전트입니다.\n"
        f"에이전트 역할: {task.get('agent_label')}\n"
        f"대상 참조: {target_ref}\n"
        f"강의 목적: {lecture_goal or 'standard'}\n"
        f"요청 지시사항: {task.get('instruction')}\n"
        f"역할 메모: {role_notes.get(task.get('agent'), '')}\n\n"
        f"커리큘럼 요약:\n{json.dumps(curriculum or {}, ensure_ascii=False, indent=2)[:1800]}\n\n"
        f"시험 요약:\n{json.dumps(exam_summary or {}, ensure_ascii=False, indent=2)[:1200]}\n\n"
        f"슬라이드 요약:\n" + ("\n".join(slide_lines) if slide_lines else "슬라이드 데이터 없음") + "\n\n"
        f"문항 요약:\n" + ("\n".join(question_lines) if question_lines else "문항 데이터 없음") + "\n\n"
        "응답 형식:\n"
        "1. 핵심 판단\n"
        "2. 바로 실행할 액션 3개 이하\n"
        "3. 주의할 리스크\n"
        "4. 필요하면 짧은 예시 문안 또는 레이아웃/문항 제안\n"
    )


def _llm_to_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(part.strip() for part in parts if part and str(part).strip()).strip()
    return str(content or "").strip()


def run_agent_task(task_id: str) -> dict:
    task = get_agent_task(task_id)
    if not task:
        raise ValueError("에이전트 작업을 찾을 수 없습니다.")

    task["status"] = "running"
    task["started_at"] = _iso_now()
    task["updated_at"] = task["started_at"]
    task["message"] = "에이전트가 요청을 처리하고 있습니다."
    _upsert_task(task)

    try:
        detail = _detail_context(task.get("target_ref") or "")
        llm = config.make_llm(AGENT_OPTIONS[task["agent"]]["model"], temperature=0.2, max_tokens=2200)
        prompt = _build_agent_prompt(task, detail)
        response = llm.invoke(prompt)
        text = _llm_to_text(response) or "응답이 비어 있습니다."
        task["status"] = "completed"
        task["message"] = "에이전트 응답을 완료했습니다."
        task["result"] = text
        task["result_preview"] = text[:400]
    except Exception as exc:
        task["status"] = "failed"
        task["message"] = f"에이전트 실행 실패: {exc}"
        task["result"] = str(exc)
        task["result_preview"] = str(exc)[:400]
    finally:
        task["finished_at"] = _iso_now()
        task["updated_at"] = task["finished_at"]
        _upsert_task(task)

    return task


def run_agent_task_async(task_id: str, on_complete: Callable[[dict], None] | None = None) -> dict:
    task = get_agent_task(task_id)
    if not task:
        raise ValueError("에이전트 작업을 찾을 수 없습니다.")

    def _runner():
        result = run_agent_task(task_id)
        if on_complete:
            try:
                on_complete(result)
            except Exception:
                pass

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return task
