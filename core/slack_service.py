from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import config


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


def record_slack_activity(kind: str, payload: dict[str, Any]) -> None:
    data = _read_json(config.SLACK_ACTIVITY_FILE, {"events": []})
    events = data.get("events") or []
    events.append(
        {
            "kind": kind,
            "time": _iso_now(),
            "payload": payload,
        }
    )
    data["events"] = events[-100:]
    data["updated_at"] = _iso_now()
    _write_json(config.SLACK_ACTIVITY_FILE, data)


def list_recent_slack_activity(limit: int = 20) -> list[dict]:
    events = _read_json(config.SLACK_ACTIVITY_FILE, {"events": []}).get("events", [])
    events = [event for event in events if isinstance(event, dict)]
    events.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
    return events[: max(1, min(100, int(limit or 20)))]


def slack_status() -> dict:
    base_url = config.PUBLIC_BASE_URL.rstrip("/")
    return {
        "enabled": bool(config.SLACK_BOT_TOKEN and config.SLACK_SIGNING_SECRET and config.SLACK_EVENTS_ENABLED),
        "token_configured": bool(config.SLACK_BOT_TOKEN),
        "signing_secret_configured": bool(config.SLACK_SIGNING_SECRET),
        "events_enabled": bool(config.SLACK_EVENTS_ENABLED),
        "default_channel": config.SLACK_DEFAULT_CHANNEL,
        "command_name": config.SLACK_COMMAND_NAME,
        "base_url": base_url,
        "command_url": f"{base_url}/slack/commands" if base_url else "",
        "events_url": f"{base_url}/slack/events" if base_url else "",
        "recent_activity": list_recent_slack_activity(8),
    }


def verify_request(flask_request) -> tuple[bool, str]:
    if not config.SLACK_SIGNING_SECRET:
        return False, "SLACK_SIGNING_SECRET가 설정되지 않았습니다."

    timestamp = flask_request.headers.get("X-Slack-Request-Timestamp", "").strip()
    signature = flask_request.headers.get("X-Slack-Signature", "").strip()
    if not timestamp or not signature:
        return False, "Slack 서명 헤더가 없습니다."
    try:
        ts = int(timestamp)
    except ValueError:
        return False, "Slack 타임스탬프가 올바르지 않습니다."

    if abs(time.time() - ts) > config.SLACK_REQUEST_TOLERANCE_SECONDS:
        return False, "Slack 요청 타임스탬프가 만료되었습니다."

    body = flask_request.get_data(cache=True, as_text=False)
    basestring = f"v0:{timestamp}:".encode("utf-8") + body
    digest = hmac.new(
        config.SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    if not hmac.compare_digest(expected, signature):
        return False, "Slack 요청 서명이 일치하지 않습니다."
    return True, ""


def _api_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _api_post(url: str, payload: dict[str, Any], *, auth: bool = True) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if auth:
        headers.update(_api_headers())
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body or "{}")
            return parsed if isinstance(parsed, dict) else {"ok": False, "body": body}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body or "{}")
        except Exception:
            parsed = {"ok": False, "error": body or str(exc)}
        return {"ok": False, "status_code": exc.code, **parsed}
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason)}


def post_message(channel: str, text: str, *, thread_ts: str = "", blocks: list[dict] | None = None) -> dict:
    if not config.SLACK_BOT_TOKEN:
        return {"ok": False, "error": "SLACK_BOT_TOKEN이 설정되지 않았습니다."}
    target_channel = (channel or config.SLACK_DEFAULT_CHANNEL or "").strip()
    if not target_channel:
        return {"ok": False, "error": "Slack 채널이 필요합니다."}
    payload: dict[str, Any] = {
        "channel": target_channel,
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    result = _api_post("https://slack.com/api/chat.postMessage", payload, auth=True)
    record_slack_activity("chat.postMessage", {"channel": target_channel, "ok": result.get("ok"), "text": text[:240]})
    return result


def post_response_url(response_url: str, text: str, *, response_type: str = "ephemeral", blocks: list[dict] | None = None) -> dict:
    if not response_url:
        return {"ok": False, "error": "response_url이 없습니다."}
    payload: dict[str, Any] = {
        "response_type": response_type,
        "text": text,
        "replace_original": False,
    }
    if blocks:
        payload["blocks"] = blocks
    result = _api_post(response_url, payload, auth=False)
    record_slack_activity("response_url", {"ok": result.get("ok", True), "text": text[:240]})
    return result


def strip_bot_mention(text: str) -> str:
    raw = str(text or "").strip()
    return " ".join(part for part in raw.split() if not (part.startswith("<@") and part.endswith(">"))).strip()


def help_text() -> str:
    cmd = config.SLACK_COMMAND_NAME or "/teachon"
    return (
        "Teach-On Slack 명령\n"
        f"• `{cmd} help` : 명령 도움말\n"
        f"• `{cmd} jobs` : 최근 생성 결과 / 분석 작업 보기\n"
        f"• `{cmd} status <uid-or-job>` : 특정 작업 상세 보기\n"
        f"• `{cmd} share <uid>` : 현재 채널에 결과물 링크 공유\n"
        f"• `{cmd} task <agent> <uid> <instruction>` : 선택 에이전트에 작업 지시\n"
        f"• `{cmd} feedback <uid> <message>` : 결과물 피드백 기록\n"
        "지원 agent: pm, curriculum, content, fact_checker, question, reviewer, layout, formatter"
    )


def _safe_host(url: str) -> str:
    parsed = urlparse(url or "")
    return parsed.netloc or url or "Slack"


def format_share_message(detail: dict, target_ref: str) -> str:
    preview_url = detail.get("preview_url") or f"/preview/{target_ref}"
    base = config.PUBLIC_BASE_URL.rstrip("/")
    absolute_preview = f"{base}{preview_url}" if base and preview_url.startswith("/") else preview_url
    ppt_url = f"{base}/download/{target_ref}" if base else f"/download/{target_ref}"
    lines = [
        f"*{detail.get('pdf_name') or detail.get('download_name') or target_ref}*",
        f"슬라이드 {len(detail.get('slides') or [])}장",
    ]
    question_count = len(detail.get("questions") or [])
    if question_count:
        lines.append(f"문항 {question_count}개")
    if absolute_preview:
        lines.append(f"미리보기: {absolute_preview}")
    lines.append(f"PPT 다운로드: {ppt_url}")
    return " · ".join(lines)

