from __future__ import annotations

import hmac
import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
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


def record_telegram_activity(kind: str, payload: dict[str, Any]) -> None:
    data = _read_json(config.TELEGRAM_ACTIVITY_FILE, {"events": []})
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
    _write_json(config.TELEGRAM_ACTIVITY_FILE, data)


def list_recent_telegram_activity(limit: int = 20) -> list[dict]:
    events = _read_json(config.TELEGRAM_ACTIVITY_FILE, {"events": []}).get("events", [])
    events = [event for event in events if isinstance(event, dict)]
    events.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
    return events[: max(1, min(100, int(limit or 20)))]


def record_thread_context(
    chat_id: str | int,
    message_id: int | None,
    role: str,
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    data = _read_json(config.TELEGRAM_THREADS_FILE, {"threads": {}})
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
            "role": str(role or "").strip() or "system",
            "message_id": int(message_id) if message_id else None,
            "text": str(text or "").strip(),
            "metadata": metadata or {},
        }
    )
    thread["events"] = events[-120:]
    thread["updated_at"] = _iso_now()
    threads[key] = thread
    data["threads"] = threads
    data["updated_at"] = _iso_now()
    _write_json(config.TELEGRAM_THREADS_FILE, data)


def allowed_chat_ids() -> set[str]:
    raw = str(config.TELEGRAM_ALLOWED_CHAT_IDS or "").replace("\n", ",")
    parts = [part.strip() for part in raw.split(",")]
    return {part for part in parts if part}


def is_allowed_chat(chat_id: str | int | None) -> bool:
    allowed = allowed_chat_ids()
    if not allowed:
        return True
    return str(chat_id or "").strip() in allowed


def telegram_status() -> dict:
    base_url = config.PUBLIC_BASE_URL.rstrip("/")
    return {
        "enabled": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_ENABLED),
        "token_configured": bool(config.TELEGRAM_BOT_TOKEN),
        "secret_configured": bool(config.TELEGRAM_WEBHOOK_SECRET),
        "webhook_enabled": bool(config.TELEGRAM_WEBHOOK_ENABLED),
        "pm_only_mode": bool(config.TELEGRAM_PM_ONLY_MODE),
        "pm_dispatch_enabled": bool(config.PM_DISPATCH_ENABLED),
        "default_chat_id": config.TELEGRAM_DEFAULT_CHAT_ID,
        "allowed_chat_ids": sorted(allowed_chat_ids()),
        "base_url": base_url,
        "webhook_url": f"{base_url}/telegram/webhook" if base_url else "",
        "recent_activity": list_recent_telegram_activity(8),
    }


def verify_request(flask_request) -> tuple[bool, str]:
    if not config.TELEGRAM_WEBHOOK_SECRET:
        return False, "TELEGRAM_WEBHOOK_SECRET가 설정되지 않았습니다."

    secret = flask_request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    if not secret:
        return False, "Telegram secret header가 없습니다."
    if not hmac.compare_digest(secret, config.TELEGRAM_WEBHOOK_SECRET):
        return False, "Telegram webhook secret이 일치하지 않습니다."
    return True, ""


def _trim_text(text: str, limit: int = 4000) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _encode_multipart(fields: dict[str, Any], files: dict[str, str], boundary: str) -> bytes:
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, path_text in files.items():
        file_path = Path(path_text)
        filename = file_path.name or field_name
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with file_path.open("rb") as handle:
            body = handle.read()
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                body,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


def _api_call(
    method: str,
    payload: dict[str, Any] | None = None,
    *,
    files: dict[str, str] | None = None,
) -> dict:
    if not config.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."}

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    headers: dict[str, str]
    if files:
        boundary = f"TeachOnTelegram{uuid.uuid4().hex}"
        body = _encode_multipart(payload or {}, files, boundary)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    else:
        body = json.dumps(payload or {}).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}

    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(text or "{}")
            return parsed if isinstance(parsed, dict) else {"ok": False, "description": text}
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body_text or "{}")
        except Exception:
            parsed = {"ok": False, "description": body_text or str(exc)}
        return {"ok": False, "status_code": exc.code, **parsed}
    except URLError as exc:
        return {"ok": False, "description": str(exc.reason)}


def send_message(
    chat_id: str | int,
    text: str,
    *,
    reply_to_message_id: int | None = None,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str = "",
    disable_web_page_preview: bool = True,
) -> dict:
    target_chat = str(chat_id or config.TELEGRAM_DEFAULT_CHAT_ID or "").strip()
    if not target_chat:
        return {"ok": False, "description": "Telegram chat_id가 필요합니다."}
    payload: dict[str, Any] = {
        "chat_id": target_chat,
        "text": _trim_text(text),
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = _api_call("sendMessage", payload)
    record_telegram_activity(
        "sendMessage",
        {"chat_id": target_chat, "ok": result.get("ok"), "text": payload["text"][:240]},
    )
    return result


def edit_message_text(
    chat_id: str | int,
    message_id: int,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str = "",
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": str(chat_id),
        "message_id": int(message_id),
        "text": _trim_text(text),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = _api_call("editMessageText", payload)
    record_telegram_activity(
        "editMessageText",
        {"chat_id": str(chat_id), "message_id": int(message_id), "ok": result.get("ok")},
    )
    return result


def send_document(
    chat_id: str | int,
    file_path: str,
    *,
    caption: str = "",
    reply_to_message_id: int | None = None,
) -> dict:
    target_chat = str(chat_id or config.TELEGRAM_DEFAULT_CHAT_ID or "").strip()
    path = Path(file_path)
    if not target_chat:
        return {"ok": False, "description": "Telegram chat_id가 필요합니다."}
    if not path.exists():
        return {"ok": False, "description": "전송할 파일을 찾을 수 없습니다."}

    payload: dict[str, Any] = {
        "chat_id": target_chat,
    }
    if caption:
        payload["caption"] = _trim_text(caption, limit=900)
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
    result = _api_call("sendDocument", payload, files={"document": str(path)})
    record_telegram_activity(
        "sendDocument",
        {
            "chat_id": target_chat,
            "ok": result.get("ok"),
            "file_name": path.name,
        },
    )
    return result


def answer_callback_query(callback_query_id: str, *, text: str = "", show_alert: bool = False) -> dict:
    payload: dict[str, Any] = {
        "callback_query_id": str(callback_query_id or "").strip(),
        "show_alert": bool(show_alert),
    }
    if text:
        payload["text"] = _trim_text(text, limit=180)
    result = _api_call("answerCallbackQuery", payload)
    record_telegram_activity(
        "answerCallbackQuery",
        {"ok": result.get("ok"), "text": payload.get("text", "")[:180]},
    )
    return result


def _callback_to_command(data: str) -> str:
    raw = str(data or "").strip()
    if raw == "tg:jobs":
        return "/jobs"
    if raw.startswith("tg:status:"):
        return f"/status {raw.split(':', 2)[2]}"
    if raw.startswith("tg:share:"):
        return f"/share {raw.split(':', 2)[2]}"
    return raw


def extract_update_context(update: dict[str, Any]) -> dict[str, Any]:
    callback = update.get("callback_query") or {}
    if isinstance(callback, dict) and callback:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        from_user = callback.get("from") or {}
        data = str(callback.get("data") or "").strip()
        return {
            "kind": "callback_query",
            "update_id": update.get("update_id"),
            "chat_id": str(chat.get("id") or "").strip(),
            "chat_type": str(chat.get("type") or "").strip(),
            "message_id": message.get("message_id"),
            "text": _callback_to_command(data),
            "callback_data": data,
            "callback_query_id": str(callback.get("id") or "").strip(),
            "username": str(from_user.get("username") or "").strip(),
            "display_name": " ".join(
                part for part in [from_user.get("first_name"), from_user.get("last_name")] if part
            ).strip(),
            "is_bot": bool(from_user.get("is_bot")),
        }

    message = update.get("message") or update.get("edited_message") or {}
    if not isinstance(message, dict) or not message:
        return {}
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    return {
        "kind": "message",
        "update_id": update.get("update_id"),
        "chat_id": str(chat.get("id") or "").strip(),
        "chat_type": str(chat.get("type") or "").strip(),
        "message_id": message.get("message_id"),
        "text": str(message.get("text") or message.get("caption") or "").strip(),
        "callback_data": "",
        "callback_query_id": "",
        "username": str(from_user.get("username") or "").strip(),
        "display_name": " ".join(
            part for part in [from_user.get("first_name"), from_user.get("last_name")] if part
        ).strip(),
        "is_bot": bool(from_user.get("is_bot")),
    }
