import io
import json
import logging
import os
import locale
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from copy import deepcopy
from datetime import datetime
from urllib.parse import parse_qs, quote

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file, session
import fitz  # PyMuPDF
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

load_dotenv()

import config
from core.agent_control import (
    available_agents,
    create_agent_task,
    get_agent_task,
    list_agent_tasks,
    run_agent_task,
    run_agent_task_async,
)
from core.claude_analyzer import analyze_pdf
from core.dashboard_service import (
    dashboard_job_detail,
    dashboard_jobs,
    dashboard_overview,
    get_connector,
    invoke_connector,
    load_connectors,
    security_summary,
    test_connector,
    upsert_connector,
)
from core.history import add_record, get_history
from core.pm_dispatcher import (
    format_agent_task_result as format_pm_task_result,
    handle_telegram_message as handle_telegram_pm_message,
)
from core.pdf_parser import (
    build_page_plan_preview,
    extract_pdf_images,
    parse_page_range,
    resolve_page_selection,
)
from core.ppt_generator import (
    LEGACY_THEME_PRESET_MAP,
    PRESETS,
    SUPPORTED_FONTS,
    generate_pptx_bytes,
)
from core.security import (
    check_rate_limit,
    dashboard_allowlist_networks,
    is_ip_allowed,
    rate_limit_bucket_for_request,
    rate_limit_settings,
    resolve_client_ip,
    verify_admin_credentials,
)
from core.slide_quality import build_outline, build_quality_summary, review_slides
from core.slide_enricher import attach_pdf_images_to_slides
from core.slide_variants import generate_slide_variants
from core.slack_service import (
    format_share_message,
    help_text as slack_help_text,
    post_message as slack_post_message,
    post_response_url as slack_post_response_url,
    record_slack_activity,
    slack_status,
    strip_bot_mention,
    verify_request as verify_slack_request,
)
from core.telegram_service import (
    answer_callback_query as telegram_answer_callback_query,
    extract_update_context as telegram_extract_update_context,
    is_allowed_chat as telegram_is_allowed_chat,
    record_telegram_activity,
    record_thread_context as telegram_record_thread_context,
    send_message as telegram_send_message,
    telegram_status,
    verify_request as verify_telegram_request,
)
from flows import build_initial_agent_trace, run_full_pipeline
from tools.docx_tool import save_exam_artifacts
from tools.slide_tool import build_exam_summary
from tools.theme_tool import list_theme_specs

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
app.secret_key = config.SESSION_SECRET
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
# Keep API JSON ASCII-safe so Render/gunicorn never has to emit raw Unicode
# while streaming large Korean slide payloads back to the browser.
app.config["JSON_AS_ASCII"] = True
app.json.ensure_ascii = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_storage_dir(raw_value: str | None, default_name: str) -> str:
    chosen = str(raw_value or "").strip() or default_name
    if os.path.isabs(chosen):
        return chosen
    return os.path.join(BASE_DIR, chosen)


UPLOAD_DIR = _resolve_storage_dir(os.getenv("UPLOAD_DIR"), "uploads")
OUTPUT_DIR = _resolve_storage_dir(os.getenv("OUTPUT_DIR"), "outputs")
ANALYZE_JOB_DIR = os.path.join(OUTPUT_DIR, "analyze_jobs")
UID_RE = re.compile(r"^[a-f0-9]{8}$")
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
SAFE_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PPTX_DIR = str(config.PPTX_DIR)
DOCX_DIR = str(config.DOCX_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ANALYZE_JOB_DIR, exist_ok=True)
os.makedirs(PPTX_DIR, exist_ok=True)
os.makedirs(DOCX_DIR, exist_ok=True)
ERROR_LOG_FILE = os.path.join(OUTPUT_DIR, "server_errors.log")
OCRMYPDF_BIN = shutil.which("ocrmypdf")
TESSERACT_BIN = shutil.which("tesseract")
INTERNAL_SCAN_ENHANCER_AVAILABLE = True
OCR_AVAILABLE = bool(OCRMYPDF_BIN and TESSERACT_BIN) or INTERNAL_SCAN_ENHANCER_AVAILABLE


def _as_utf8_stream(stream):
    if stream is None:
        return None
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
            return stream
    except Exception:
        pass

    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            return stream
    return stream


def _ensure_utf8_runtime():
    for candidate in (
        os.getenv("LC_ALL"),
        os.getenv("LANG"),
        "C.UTF-8",
        "en_US.UTF-8",
        "UTF-8",
    ):
        if not candidate:
            continue
        try:
            locale.setlocale(locale.LC_ALL, candidate)
            break
        except Exception:
            continue

    sys.stdout = _as_utf8_stream(sys.stdout) or sys.stdout
    sys.stderr = _as_utf8_stream(sys.stderr) or sys.stderr

    seen = set()
    for logger in (logging.getLogger(), app.logger):
        for handler in logger.handlers:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            stream = getattr(handler, "stream", None)
            if stream is None:
                continue
            wrapped = _as_utf8_stream(stream)
            if wrapped is not None and wrapped is not stream and hasattr(handler, "setStream"):
                try:
                    handler.setStream(wrapped)
                except Exception:
                    pass


def _safe_error_text(exc: Exception) -> str:
    if isinstance(exc, UnicodeEncodeError):
        return f"텍스트 인코딩 오류 (서버 인코딩 설정 문제): {exc.encoding} codec, position {exc.start}"

    try:
        text = str(exc).strip()
    except Exception:
        text = exc.__class__.__name__
    lowered = text.lower()
    if "invalid x-api-key" in lowered or "authentication_error" in lowered:
        return "서버에 설정된 Anthropic API 키가 유효하지 않습니다. Render 환경변수 `ANTHROPIC_API_KEY`를 다시 입력해 주세요."
    return text or exc.__class__.__name__


def _json_response(payload: dict | list, status: int = 200):
    body = json.dumps(payload, ensure_ascii=True)
    return app.response_class(
        response=body,
        status=status,
        mimetype="application/json",
    )


def _is_valid_pdf_file(file_storage) -> bool:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return False
    try:
        stream = file_storage.stream
        pos = stream.tell()
        head = stream.read(5)
        stream.seek(pos)
    except Exception:
        return False
    return head == b"%PDF-"


def _is_valid_image_file(file_storage) -> bool:
    if not file_storage or not getattr(file_storage, "filename", ""):
        return False
    try:
        stream = file_storage.stream
        pos = stream.tell()
        image = Image.open(stream)
        image.verify()
        stream.seek(pos)
        return True
    except Exception:
        try:
            stream.seek(pos)
        except Exception:
            pass
        return False


def _dashboard_auth_enabled() -> bool:
    return bool(config.ADMIN_TOKEN or config.ADMIN_PASSWORD or config.ADMIN_PASSWORD_HASH)


def _dashboard_session_authenticated() -> bool:
    return bool(session.get("teachon_admin_authenticated"))


def _dashboard_auth_state() -> dict:
    return {
        "auth_enabled": _dashboard_auth_enabled(),
        "session_authenticated": _dashboard_session_authenticated(),
        "token_authenticated": _dashboard_token_ok(),
        "username": session.get("teachon_admin_username", ""),
    }


def _dashboard_token_ok() -> bool:
    if not bool(config.ADMIN_TOKEN):
        return False
    token = request.headers.get("X-TeachOn-Token", "").strip()
    return bool(token) and token == config.ADMIN_TOKEN


def _dashboard_guard(mutate: bool = False):
    if _dashboard_token_ok() or _dashboard_session_authenticated() or not _dashboard_auth_enabled():
        return None
    return _json_response(
        {
            "error": "대시보드 로그인 또는 관리자 토큰이 필요합니다.",
            "code": "dashboard_auth_required",
        },
        status=401,
    )


def _record_exception(stage: str, exc: Exception) -> str:
    _ensure_utf8_runtime()
    error_id = uuid.uuid4().hex[:8]
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    line = f"[{datetime.utcnow().isoformat()}Z] {stage} error_id={error_id}\n{formatted}\n"

    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(line)
    except Exception:
        pass

    try:
        print(line, file=sys.stderr)
    except Exception:
        try:
            ascii_line = line.encode("ascii", "backslashreplace").decode("ascii")
            print(ascii_line, file=sys.stderr)
        except Exception:
            pass

    return error_id


def _slack_json_response(payload: dict, status: int = 200):
    return app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )


def _summarize_jobs_for_slack() -> str:
    snapshot = dashboard_jobs(limit_outputs=5, limit_active=5)
    parts: list[str] = []
    active_jobs = snapshot.get("analyze_jobs") or []
    recent_outputs = snapshot.get("recent_outputs") or []
    if active_jobs:
        parts.append("실행 중 / 최근 분석 작업")
        for item in active_jobs[:5]:
            parts.append(
                f"• {item.get('job_id')} · {item.get('status','queued')} · "
                f"{item.get('stage') or 'stage 없음'}"
            )
    if recent_outputs:
        if parts:
            parts.append("")
        parts.append("최근 생성 결과")
        for item in recent_outputs[:5]:
            parts.append(
                f"• {item.get('uid')} · {item.get('pdf_name') or item.get('download_name')} · "
                f"{item.get('slide_count', 0)}장 / {item.get('question_count', 0)}문항"
            )
    return "\n".join(parts) if parts else "현재 표시할 Teach-On 작업이 없습니다."


def _summarize_job_detail_for_slack(target_ref: str) -> str:
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


def _dashboard_agent_task_payload(body: dict) -> dict:
    return {
        "agent": str(body.get("agent") or "pm").strip().lower(),
        "target_ref": str(body.get("target_ref") or "").strip(),
        "instruction": str(body.get("instruction") or "").strip(),
        "requested_by": str(body.get("requested_by") or session.get("teachon_admin_username") or "dashboard").strip(),
        "source": str(body.get("source") or "dashboard").strip().lower() or "dashboard",
    }


def _create_and_run_agent_task(body: dict, async_mode: bool = False, on_complete=None) -> dict:
    task = create_agent_task(_dashboard_agent_task_payload(body))
    if async_mode:
        run_agent_task_async(task["id"], on_complete=on_complete)
        return get_agent_task(task["id"]) or task
    return run_agent_task(task["id"])


def _post_agent_task_result_to_slack(task: dict):
    target_ref = task.get("target_ref") or "대상 없음"
    text = (
        f"*{task.get('agent_label')}* 작업 결과\n"
        f"대상: {target_ref}\n"
        f"상태: {task.get('status')}\n\n"
        f"{task.get('result_preview') or task.get('message') or ''}"
    )
    response_url = task.get("response_url") or ""
    if response_url:
        slack_post_response_url(response_url, text, response_type="ephemeral")
        return
    channel_id = task.get("channel_id") or config.SLACK_DEFAULT_CHANNEL
    if channel_id:
        slack_post_message(channel_id, text, thread_ts=task.get("thread_ts") or "")


def _post_agent_task_result_to_telegram(task: dict):
    chat_id = task.get("transport_chat_id") or config.TELEGRAM_DEFAULT_CHAT_ID
    if not chat_id:
        return
    reply_to_message_id = None
    raw_message_id = str(task.get("transport_message_id") or "").strip()
    if raw_message_id.isdigit():
        reply_to_message_id = int(raw_message_id)
    telegram_send_message(
        chat_id,
        format_pm_task_result(task),
        reply_to_message_id=reply_to_message_id,
    )
    telegram_record_thread_context(
        chat_id,
        reply_to_message_id,
        "assistant",
        format_pm_task_result(task),
        metadata={"task_id": task.get("id"), "status": task.get("status")},
    )


def _handle_slack_task_command(agent: str, target_ref: str, instruction: str, *, channel_id: str = "", thread_ts: str = "", response_url: str = "") -> dict:
    task = create_agent_task(
        {
            "agent": agent,
            "target_ref": target_ref,
            "instruction": instruction,
            "requested_by": "slack",
            "source": "slack",
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "response_url": response_url,
        }
    )
    run_agent_task_async(task["id"], on_complete=_post_agent_task_result_to_slack)
    return task


def _handle_slack_command(text: str, *, channel_id: str = "", thread_ts: str = "", response_url: str = "") -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return slack_help_text(), "ephemeral"

    parts = raw.split()
    command = parts[0].lower()
    args = parts[1:]

    if command in {"help", "?", "commands"}:
        return slack_help_text(), "ephemeral"
    if command in {"jobs", "recent"}:
        return _summarize_jobs_for_slack(), "ephemeral"
    if command == "status":
        if not args:
            return "예: /teachon status <uid-or-job>", "ephemeral"
        return _summarize_job_detail_for_slack(args[0]), "ephemeral"
    if command == "share":
        if not args:
            return "예: /teachon share <uid>", "ephemeral"
        detail = dashboard_job_detail(args[0])
        if not detail or "slides" not in detail:
            return "공유할 결과물을 찾지 못했습니다.", "ephemeral"
        message = format_share_message(detail, args[0])
        result = slack_post_message(channel_id or config.SLACK_DEFAULT_CHANNEL, message, thread_ts=thread_ts)
        if result.get("ok"):
            return "현재 채널에 결과물 링크를 공유했습니다.", "ephemeral"
        return f"Slack 공유 실패: {result.get('error') or 'unknown error'}", "ephemeral"
    if command == "feedback":
        if len(args) < 2:
            return "예: /teachon feedback <uid> <message>", "ephemeral"
        task = _handle_slack_task_command("pm", args[0], f"사용자 피드백을 기록하고 다음 액션을 제안하세요: {' '.join(args[1:])}", channel_id=channel_id, thread_ts=thread_ts, response_url=response_url)
        return f"피드백을 PM 에이전트에 전달했습니다. task_id={task['id']}", "ephemeral"
    if command == "task":
        if len(args) < 3:
            return "예: /teachon task <agent> <uid> <instruction>", "ephemeral"
        agent = args[0].strip().lower()
        if agent not in {item["key"] for item in available_agents()}:
            return "지원하지 않는 에이전트입니다. pm, curriculum, content, fact_checker, question, reviewer, layout, formatter 중에서 선택해 주세요.", "ephemeral"
        target_ref = args[1].strip()
        instruction = " ".join(args[2:]).strip()
        task = _handle_slack_task_command(agent, target_ref, instruction, channel_id=channel_id, thread_ts=thread_ts, response_url=response_url)
        return f"{task['agent_label']} 작업을 접수했습니다. task_id={task['id']}", "ephemeral"
    return slack_help_text(), "ephemeral"


_ensure_utf8_runtime()


@app.before_request
def _refresh_runtime_encoding():
    _ensure_utf8_runtime()


@app.before_request
def _apply_security_controls():
    path = request.path or "/"
    client_ip = resolve_client_ip(request)
    request.environ["teachon.client_ip"] = client_ip

    if path.startswith("/dashboard") or path.startswith("/api/dashboard"):
        allowlist = dashboard_allowlist_networks()
        if allowlist and not is_ip_allowed(client_ip, allowlist):
            if path.startswith("/api/"):
                return _json_response(
                    {
                        "error": "이 IP는 대시보드 접근이 허용되지 않습니다.",
                        "code": "dashboard_ip_forbidden",
                    },
                    status=403,
                )
            return app.response_class(
                response="Dashboard access is not allowed from this IP address.",
                status=403,
                mimetype="text/plain",
            )

    bucket = rate_limit_bucket_for_request(path, request.method)
    allowed, retry_after, bucket_config = check_rate_limit(client_ip, bucket)
    if allowed:
        return None

    if path.startswith("/api/"):
        response = _json_response(
            {
                "error": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                "code": "rate_limited",
                "bucket": bucket,
                "retry_after": retry_after,
            },
            status=429,
        )
    else:
        response = app.response_class(
            response="Too many requests. Please try again shortly.",
            status=429,
            mimetype="text/plain",
        )
    response.headers["Retry-After"] = str(retry_after)
    response.headers["X-RateLimit-Bucket"] = bucket
    response.headers["X-RateLimit-Limit"] = str(bucket_config["limit"])
    response.headers["X-RateLimit-Window"] = str(bucket_config["window"])
    return response


@app.after_request
def _disable_response_caching(response):
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'; "
        "form-action 'self'"
    )
    return response


@app.errorhandler(413)
def _request_too_large(_exc):
    return _json_response(
        {
            "error": f"업로드 크기가 너무 큽니다. 최대 {config.MAX_UPLOAD_MB}MB까지 업로드할 수 있습니다.",
        },
        status=413,
    )


def _resolve_preset_id(preset_id: str) -> str:
    return LEGACY_THEME_PRESET_MAP.get(preset_id, preset_id or "corporate")


def _coerce_design(body: dict) -> dict:
    design = body.get("design")
    if isinstance(design, dict):
        return design
    return {"preset": body.get("theme", "navy")}


def _find_logo_path(logo_uid: str):
    for ext in ("png", "jpg", "jpeg", "gif", "webp"):
        candidate = os.path.join(UPLOAD_DIR, f"logo_{logo_uid}.{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


def _asset_bundle_dir(bundle_uid: str) -> str:
    return os.path.join(UPLOAD_DIR, f"assets_{bundle_uid}")


def _cleanup_asset_bundle(bundle_uid: str):
    shutil.rmtree(_asset_bundle_dir(bundle_uid), ignore_errors=True)


def _pdf_asset_path(bundle_uid: str, asset_name: str):
    bundle = str(bundle_uid or "")
    asset = os.path.basename(str(asset_name or ""))
    if not UID_RE.match(bundle):
        return None
    if not asset or asset != asset_name or not SAFE_ASSET_NAME_RE.match(asset):
        return None
    path = os.path.join(_asset_bundle_dir(bundle), asset)
    if not os.path.exists(path):
        return None
    return path


def _resolve_media_assets(assets: list[dict] | None) -> list[dict]:
    resolved = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        path = _pdf_asset_path(asset.get("bundle_uid"), asset.get("asset_name"))
        if not path:
            continue
        resolved.append({**asset, "path": path})
    return resolved


def _slides_json_path(uid: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{uid}_slides.json")


def _uploaded_pdf_path(uid: str) -> str:
    return os.path.join(UPLOAD_DIR, f"{uid}.pdf")


def _analyze_job_path(job_id: str) -> str:
    return os.path.join(ANALYZE_JOB_DIR, f"{job_id}.json")


def _write_json_atomic(path: str, payload: dict):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(temp_path, path)


def _load_analyze_job(job_id: str):
    path = _analyze_job_path(job_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_analyze_job(job_id: str, payload: dict):
    _write_json_atomic(_analyze_job_path(job_id), payload)


def _update_analyze_job(job_id: str, **changes):
    payload = _load_analyze_job(job_id) or {"job_id": job_id}
    payload.update(changes)
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if "created_at" not in payload:
        payload["created_at"] = payload["updated_at"]
    _save_analyze_job(job_id, payload)


def _load_saved_payload(uid: str):
    path = _slides_json_path(uid)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_saved_payload(uid: str, payload: dict):
    with open(_slides_json_path(uid), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _default_download_name(pdf_name: str, fallback_filename: str = "강의교안.pptx") -> str:
    base = os.path.splitext(os.path.basename(pdf_name or ""))[0].strip()
    if not base:
        base = os.path.splitext(os.path.basename(fallback_filename))[0].strip() or "강의교안"
    if not base.endswith("_강의교안"):
        base = f"{base}_강의교안"
    return f"{base}.pptx"


def _sanitize_download_name(download_name: str, fallback_filename: str) -> str:
    fallback = os.path.basename(fallback_filename) or "download.pptx"
    raw = str(download_name or "").strip()
    if not raw:
        return fallback
    safe = INVALID_FILENAME_CHARS.sub(" ", raw)
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        return fallback
    if not safe.lower().endswith(".pptx"):
        safe = f"{safe}.pptx"
    return safe


def _is_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _parse_exam_settings(data, pdf_name: str = "") -> dict:
    return {
        "exam_enabled": _is_truthy(data.get("exam_enabled", "true")),
        "question_count": _coerce_int(data.get("question_count", 10), 10, 1, 40),
        "difficulty_easy": _coerce_int(data.get("difficulty_easy", 20), 20, 0, 100),
        "difficulty_medium": _coerce_int(data.get("difficulty_medium", 60), 60, 0, 100),
        "difficulty_hard": _coerce_int(data.get("difficulty_hard", 20), 20, 0, 100),
        "shuffle_versions": _is_truthy(data.get("shuffle_versions", "false")),
        "institution_name": str(data.get("institution_name", "") or "").strip(),
        "exam_date": str(data.get("exam_date", "") or "").strip(),
        "time_limit_minutes": _coerce_int(data.get("time_limit_minutes", 0), 0, 0, 600),
        "course_name": str(data.get("course_name") or pdf_name or "Teach-On 시험지").strip(),
    }


def _pptx_output_path(uid: str) -> str:
    return os.path.join(PPTX_DIR, f"{uid}.pptx")


def _artifact_docx_path(uid: str, kind: str) -> str:
    return os.path.join(DOCX_DIR, f"{uid}_{kind}.docx")


def _artifact_download_name(payload: dict, kind: str, requested_name: str | None = None) -> str:
    base_ppt_name = _sanitize_download_name(
        requested_name,
        payload.get("download_name") or _default_download_name(payload.get("pdf_name", "")),
    )
    base = os.path.splitext(base_ppt_name)[0]
    if kind == "ppt":
        return f"{base}.pptx"

    suffix_map = {
        "exam": "_문제지",
        "answer": "_정답지",
        "exam_a": "_문제지_A형",
        "exam_b": "_문제지_B형",
    }
    suffix = suffix_map.get(kind, f"_{kind}")
    return f"{base}{suffix}.docx"


def _persist_ppt_artifact(uid: str, slides_data: list[dict], design: dict, assets: list[dict]) -> dict:
    resolved_assets = _resolve_media_assets(assets)
    buf = generate_pptx_bytes(slides_data, design, resolved_assets)
    raw = buf.getvalue()
    with open(_pptx_output_path(uid), "wb") as handle:
        handle.write(raw)
    buf.seek(0)
    return {
        "kind": "ppt",
        "filename": f"{uid}.pptx",
        "path": _pptx_output_path(uid),
        "size": len(raw),
    }


def _persist_exam_artifacts(uid: str, questions: list[dict], exam_settings: dict) -> dict[str, dict]:
    if not exam_settings.get("exam_enabled") or not questions:
        return {}
    return save_exam_artifacts(uid, questions, exam_settings)


def _artifact_response_fields(uid: str, artifacts: dict[str, dict]) -> dict:
    response = {
        "artifacts": {
            kind: {k: v for k, v in meta.items() if k != "path"}
            for kind, meta in (artifacts or {}).items()
        }
    }
    if "ppt" in artifacts:
        response["pptx_uid"] = uid
    if "exam" in artifacts:
        response["exam_docx_uid"] = uid
    if "answer" in artifacts:
        response["answer_docx_uid"] = uid
    if "exam_a" in artifacts:
        response["exam_a_uid"] = uid
    if "exam_b" in artifacts:
        response["exam_b_uid"] = uid
    return response


def _with_formatter_state(agent_trace: list[dict] | None, message: str, status: str = "completed") -> list[dict]:
    trace = deepcopy(agent_trace or build_initial_agent_trace())
    now = datetime.utcnow().isoformat() + "Z"
    found = False
    for row in trace:
        if row.get("key") != "formatter":
            continue
        row["status"] = status
        row["message"] = message
        row["started_at"] = row.get("started_at") or now
        row["finished_at"] = now if status in {"completed", "failed"} else None
        row["updated_at"] = now
        row["attempt"] = max(1, int(row.get("attempt") or 0) + (0 if row.get("started_at") else 1))
        found = True
        break
    if not found:
        trace.append(
            {
                "key": "formatter",
                "label": "Formatter",
                "status": status,
                "message": message,
                "started_at": now,
                "finished_at": now if status in {"completed", "failed"} else None,
                "updated_at": now,
                "attempt": 1,
            }
        )
    return trace


def _prepare_slide_package(slides_data: list[dict], assets: list[dict] | None, selected_pages: list[int] | None = None):
    reviewed = review_slides(slides_data, selected_pages=selected_pages)
    image_enriched = attach_pdf_images_to_slides(reviewed["slides"], assets)
    final_review = review_slides(image_enriched, selected_pages=selected_pages)
    prepared_slides = attach_pdf_images_to_slides(final_review["slides"], assets)
    return {
        "slides": prepared_slides,
        "outline": build_outline(prepared_slides),
        "quality": build_quality_summary(prepared_slides),
    }


def _candidate_asset_pages(slides_data: list[dict], selected_pages: list[int] | None, radius: int = 1, max_pages: int = 72) -> list[int]:
    selected = sorted({int(page) for page in (selected_pages or []) if int(page) >= 1})
    if not selected:
        return []

    max_page = max(selected)
    allowed = set(selected)
    picked = []
    seen = set()

    for slide in slides_data or []:
        if slide.get("type", "content") != "content":
            continue

        source_pages = parse_page_range(slide.get("source_pages", ""), max_page)
        if not source_pages:
            continue

        for page in source_pages:
            for candidate in range(page - radius, page + radius + 1):
                if candidate not in allowed or candidate in seen:
                    continue
                seen.add(candidate)
                picked.append(candidate)
                if len(picked) >= max_pages:
                    return picked

    if picked:
        return picked

    # Fallback: evenly sample from the selected range instead of scanning the whole document.
    if len(selected) <= max_pages:
        return selected

    step = max(1, len(selected) // max_pages)
    sampled = selected[::step][:max_pages]
    return sampled or selected[:max_pages]


def _enhance_pdf_for_scans(pdf_path: str, job_uid: str) -> tuple[str, bool, str | None]:
    enhanced_path = os.path.join(UPLOAD_DIR, f"{job_uid}_ocr.pdf")
    if OCRMYPDF_BIN and TESSERACT_BIN:
        command = [
            OCRMYPDF_BIN,
            "--skip-text",
            "--force-ocr",
            "--optimize",
            "0",
            "--quiet",
            pdf_path,
            enhanced_path,
        ]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            if os.path.exists(enhanced_path):
                return enhanced_path, True, None
            return pdf_path, False, "OCR 결과 파일을 찾지 못했습니다."
        except Exception as exc:
            if os.path.exists(enhanced_path):
                os.remove(enhanced_path)
            return pdf_path, False, str(exc)

    if not INTERNAL_SCAN_ENHANCER_AVAILABLE:
        return pdf_path, False, "OCR 또는 스캔 보정 엔진을 사용할 수 없습니다."

    rendered_pages = []
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as source_img:
                enhanced = ImageOps.autocontrast(source_img.convert("L"), cutoff=1)
                enhanced = ImageEnhance.Contrast(enhanced).enhance(1.45)
                enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.4)
                enhanced = enhanced.filter(ImageFilter.SHARPEN).convert("RGB")
                rendered_pages.append(enhanced.copy())

        if not rendered_pages:
            return pdf_path, False, "보정할 PDF 페이지를 찾지 못했습니다."

        first_page, *remaining_pages = rendered_pages
        first_page.save(
            enhanced_path,
            "PDF",
            resolution=200.0,
            save_all=True,
            append_images=remaining_pages,
        )
        if os.path.exists(enhanced_path):
            return enhanced_path, True, None
        return pdf_path, False, "내장 스캔 보정 PDF를 생성하지 못했습니다."
    except Exception as exc:
        if os.path.exists(enhanced_path):
            os.remove(enhanced_path)
        return pdf_path, False, str(exc)
    finally:
        doc.close()
        for image in rendered_pages:
            try:
                image.close()
            except Exception:
                pass


def _run_analysis_pipeline(
    uid: str,
    pdf_path: str,
    slide_count: int | None,
    auto_slide_count: bool,
    enhance_scans: bool,
    page_range: str | None,
    extra_prompt: str | None,
    lecture_goal: str | None,
    exam_settings: dict | None,
    pdf_name: str,
    progress=None,
):
    analysis_pdf_path = pdf_path
    ocr_used = False
    ocr_error = None

    def notify(stage: str, message: str, agents: list[dict] | None = None):
        if callable(progress):
            progress(stage, message, agents=agents)

    try:
        notify("start", "PDF를 확인하고 분석을 준비하고 있습니다...")
        if enhance_scans:
            notify("enhance_scans", "스캔형 PDF를 보정하고 있습니다...")
            analysis_pdf_path, ocr_used, ocr_error = _enhance_pdf_for_scans(pdf_path, uid)

        notify("resolve_page_selection", "사용할 페이지 범위를 정리하고 있습니다...")
        page_plan = resolve_page_selection(analysis_pdf_path, page_range or None, max_pages_per_chunk=100)
        page_plan_preview = build_page_plan_preview(analysis_pdf_path, page_plan)
        notify("multi_agent_start", "멀티 에이전트가 draft를 만들고 있습니다...", build_initial_agent_trace())
        result = run_full_pipeline(
            uid=uid,
            pdf_path=analysis_pdf_path,
            slide_count=slide_count,
            page_range=page_range or None,
            extra_prompt=extra_prompt or None,
            lecture_goal=lecture_goal or "standard",
            page_plan=page_plan,
            page_plan_preview=page_plan_preview,
            exam_settings=exam_settings,
            asset_bundle_dir=_asset_bundle_dir(uid),
            pdf_name=pdf_name,
            progress_cb=notify,
        )
        result["auto_slide_count"] = auto_slide_count
        result["ocr_available"] = OCR_AVAILABLE
        result["ocr_used"] = ocr_used
        result["ocr_error"] = ocr_error
        result["enhance_scans_requested"] = enhance_scans
        return result
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if analysis_pdf_path != pdf_path and os.path.exists(analysis_pdf_path):
            os.remove(analysis_pdf_path)


def _run_analyze_job(
    job_id: str,
    pdf_path: str,
    slide_count: int | None,
    auto_slide_count: bool,
    enhance_scans: bool,
    page_range: str | None,
    extra_prompt: str | None,
    lecture_goal: str | None,
    exam_settings: dict | None,
    pdf_name: str,
):
    current_stage = "queued"
    latest_agents = build_initial_agent_trace()

    def progress(stage: str, message: str, agents: list[dict] | None = None):
        nonlocal current_stage
        nonlocal latest_agents
        current_stage = stage
        if agents is not None:
            latest_agents = agents
        _update_analyze_job(job_id, status="running", stage=stage, message=message, agents=latest_agents)

    try:
        _update_analyze_job(job_id, status="running", stage="queued", message="분석 작업을 시작하고 있습니다...")
        result = _run_analysis_pipeline(
            job_id,
            pdf_path,
            slide_count,
            auto_slide_count,
            enhance_scans,
            page_range,
            extra_prompt,
            lecture_goal,
            exam_settings,
            pdf_name,
            progress=progress,
        )
        _update_analyze_job(
            job_id,
            status="completed",
            stage="completed",
            message="분석이 완료되었습니다.",
            result=result,
            agents=result.get("agent_trace", latest_agents),
            finished_at=datetime.utcnow().isoformat() + "Z",
        )
    except Exception as exc:
        _cleanup_asset_bundle(job_id)
        error_id = _record_exception(f"api_analyze_job:{current_stage}", exc)
        _update_analyze_job(
            job_id,
            status="failed",
            stage=current_stage,
            message="분석 작업이 실패했습니다.",
            error=_safe_error_text(exc),
            error_id=error_id,
            agents=latest_agents,
            finished_at=datetime.utcnow().isoformat() + "Z",
        )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", dashboard_auth_enabled=_dashboard_auth_enabled())


@app.route("/preview/<uid>")
def preview(uid):
    return render_template("preview.html", uid=uid)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if "file" not in request.files:
        return jsonify({"error": "파일이 없습니다"}), 400

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "PDF 파일만 지원합니다"}), 400
    if not _is_valid_pdf_file(file):
        return jsonify({"error": "올바른 PDF 파일이 아닙니다"}), 400

    auto_slide_count = _is_truthy(request.form.get("auto_slide_count"))
    enhance_scans = _is_truthy(request.form.get("enhance_scans"))
    try:
        slide_count = int(request.form.get("slide_count", 10))
    except (TypeError, ValueError):
        slide_count = 10
    slide_count = None if auto_slide_count else max(5, min(50, slide_count))

    page_range = request.form.get("page_range", "").strip()
    extra_prompt = request.form.get("extra_prompt", "").strip()
    lecture_goal = request.form.get("lecture_goal", "standard").strip() or "standard"
    exam_settings = _parse_exam_settings(request.form, file.filename)

    uid = uuid.uuid4().hex[:8]
    pdf_path = os.path.join(UPLOAD_DIR, f"{uid}.pdf")
    file.save(pdf_path)

    try:
        result = _run_analysis_pipeline(
            uid,
            pdf_path,
            slide_count,
            auto_slide_count,
            enhance_scans,
            page_range or None,
            extra_prompt or None,
            lecture_goal,
            exam_settings,
            file.filename,
        )
        return _json_response(result)
    except Exception as exc:
        _cleanup_asset_bundle(uid)
        error_id = _record_exception("api_analyze", exc)
        return _json_response(
            {"error": _safe_error_text(exc), "error_id": error_id},
            status=500,
        )


@app.route("/api/analyze/start", methods=["POST"])
def api_analyze_start():
    if "file" not in request.files:
        return _json_response({"error": "파일이 없습니다"}, status=400)

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return _json_response({"error": "PDF 파일만 지원합니다"}, status=400)
    if not _is_valid_pdf_file(file):
        return _json_response({"error": "올바른 PDF 파일이 아닙니다"}, status=400)

    auto_slide_count = _is_truthy(request.form.get("auto_slide_count"))
    enhance_scans = _is_truthy(request.form.get("enhance_scans"))
    try:
        slide_count = int(request.form.get("slide_count", 10))
    except (TypeError, ValueError):
        slide_count = 10
    slide_count = None if auto_slide_count else max(5, min(50, slide_count))

    page_range = request.form.get("page_range", "").strip()
    extra_prompt = request.form.get("extra_prompt", "").strip()
    lecture_goal = request.form.get("lecture_goal", "standard").strip() or "standard"
    exam_settings = _parse_exam_settings(request.form, file.filename)

    job_id = uuid.uuid4().hex[:8]
    pdf_path = _uploaded_pdf_path(job_id)
    file.save(pdf_path)

    _save_analyze_job(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "message": "분석 작업을 대기열에 올렸습니다...",
            "agents": build_initial_agent_trace(),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
    )

    worker = threading.Thread(
        target=_run_analyze_job,
        args=(
            job_id,
            pdf_path,
            slide_count,
            auto_slide_count,
            enhance_scans,
            page_range or None,
            extra_prompt or None,
            lecture_goal,
            exam_settings,
            file.filename,
        ),
        daemon=True,
    )
    worker.start()

    return _json_response({"ok": True, "job_id": job_id, "status": "queued", "agents": build_initial_agent_trace()})


@app.route("/api/analyze/status/<job_id>", methods=["GET"])
def api_analyze_status(job_id):
    if not UID_RE.match(job_id):
        return _json_response({"error": "invalid job id"}, status=400)

    payload = _load_analyze_job(job_id)
    if not payload:
        if os.path.exists(_uploaded_pdf_path(job_id)):
            return _json_response(
                {
                    "job_id": job_id,
                    "status": "running",
                    "stage": "recovering",
                    "message": "분석 작업 정보를 다시 불러오는 중입니다...",
                }
            )
        return _json_response({"error": "분석 작업을 찾을 수 없습니다."}, status=404)

    return _json_response(payload)


@app.route("/api/page-plan-preview", methods=["POST"])
def api_page_plan_preview():
    if "file" not in request.files:
        return _json_response({"error": "파일이 없습니다"}, status=400)

    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return _json_response({"error": "PDF 파일만 지원합니다"}, status=400)
    if not _is_valid_pdf_file(file):
        return _json_response({"error": "올바른 PDF 파일이 아닙니다"}, status=400)

    page_range = request.form.get("page_range", "").strip()
    uid = uuid.uuid4().hex[:8]
    pdf_path = _uploaded_pdf_path(uid)
    file.save(pdf_path)

    try:
        page_plan = resolve_page_selection(pdf_path, page_range or None, max_pages_per_chunk=100)
        preview = build_page_plan_preview(pdf_path, page_plan)
        return _json_response(
            {
                "ok": True,
                "page_plan": {
                    "mode": page_plan["mode"],
                    "page_hint": page_plan.get("page_hint", ""),
                    "selected_pages": page_plan["selected_pages"],
                    "selection_note": page_plan.get("selection_note", ""),
                },
                "preview": preview,
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_page_plan_preview", exc)
        return _json_response({"error": _safe_error_text(exc), "error_id": error_id}, status=500)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


@app.route("/api/presets")
def api_presets():
    return jsonify(list_theme_specs())


@app.route("/api/fonts")
def api_fonts():
    return jsonify(SUPPORTED_FONTS)


@app.route("/api/capabilities")
def api_capabilities():
    return jsonify(
        {
            "ocr_available": OCR_AVAILABLE,
        }
    )


@app.route("/api/upload-logo", methods=["POST"])
def api_upload_logo():
    file = request.files.get("logo")
    if not file or not file.filename:
        return jsonify({"error": "파일 없음"}), 400
    if "." not in file.filename:
        return jsonify({"error": "이미지 파일만 지원"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        return jsonify({"error": "이미지 파일만 지원"}), 400
    if not _is_valid_image_file(file):
        return jsonify({"error": "손상되었거나 지원하지 않는 이미지입니다"}), 400

    uid = uuid.uuid4().hex[:8]
    logo_path = os.path.join(UPLOAD_DIR, f"logo_{uid}.{ext}")
    file.save(logo_path)
    return jsonify({"ok": True, "logo_uid": uid, "ext": ext})


@app.route("/api/logo/<logo_uid>")
def api_logo(logo_uid):
    if not UID_RE.match(logo_uid):
        return jsonify({"error": "invalid uid"}), 400
    path = _find_logo_path(logo_uid)
    if not path:
        return jsonify({"error": "not found"}), 404
    return send_file(path)


@app.route("/api/pdf-asset/<bundle_uid>/<asset_name>")
def api_pdf_asset(bundle_uid, asset_name):
    path = _pdf_asset_path(bundle_uid, asset_name)
    if not path:
        return jsonify({"error": "not found"}), 404
    return send_file(path)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.get_json()
    if not body:
        return jsonify({"error": "데이터 없음"}), 400

    slides_data = body.get("slides", [])
    design = _coerce_design(body)
    assets = body.get("assets", [])
    page_plan = body.get("page_plan", {})
    page_plan_preview = body.get("page_plan_preview", {})
    lecture_goal = body.get("lecture_goal", "standard")
    pdf_name = body.get("pdf_name", "강의교안")
    questions = body.get("questions", [])
    exam_summary = body.get("exam_summary") or build_exam_summary(questions)
    exam_settings = _parse_exam_settings(body, pdf_name)
    curriculum = body.get("curriculum", {})
    agent_trace = body.get("agent_trace") or build_initial_agent_trace()
    pm_summary = body.get("pm_summary", {})

    if not slides_data:
        return jsonify({"error": "슬라이드 데이터 없음"}), 400

    uid = uuid.uuid4().hex[:8]
    download_name = _default_download_name(pdf_name)

    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        prepared_slides = prepared["slides"]
        ppt_meta = _persist_ppt_artifact(uid, prepared_slides, design, assets)
        docx_meta = _persist_exam_artifacts(uid, questions, exam_settings)
        artifacts = {"ppt": ppt_meta, **docx_meta}
        final_trace = _with_formatter_state(agent_trace, "PPT 및 Word 산출물을 생성했습니다.")

        _save_saved_payload(
            uid,
            {
                "slides": prepared_slides,
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "design": design,
                "assets": assets,
                "page_plan": page_plan,
                "page_plan_preview": page_plan_preview,
                "lecture_goal": lecture_goal,
                "pdf_name": pdf_name,
                "download_name": download_name,
                "questions": questions,
                "exam_summary": exam_summary,
                "exam_settings": exam_settings,
                "agent_trace": final_trace,
                "curriculum": curriculum,
                "pm_summary": pm_summary,
                "artifacts": artifacts,
            },
        )

        preset_id = _resolve_preset_id(design.get("preset", "corporate"))
        add_record(pdf_name, uid, len(prepared_slides), preset_id)
        preset_name = PRESETS.get(preset_id, PRESETS["corporate"])["name"]
        return jsonify(
            {
                "ok": True,
                "preview_uid": uid,
                "slide_count": len(prepared_slides),
                "preset": preset_name,
                "download_name": download_name,
                "page_plan_preview": page_plan_preview,
                "lecture_goal": lecture_goal,
                "question_count": len(questions or []),
                "exam_summary": exam_summary,
                "agent_trace": final_trace,
                **_artifact_response_fields(uid, artifacts),
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_generate", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/slides/<uid>")
def api_slides(uid):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid uid"}), 400
    try:
        payload = _load_saved_payload(uid)
        if not payload:
            return jsonify({"error": "not found"}), 404
        if not payload.get("download_name"):
            payload["download_name"] = _default_download_name(
                payload.get("pdf_name", ""),
                payload.get("filename", "강의교안.pptx"),
            )
        if not payload.get("outline"):
            payload["outline"] = build_outline(payload.get("slides", []))
        if not payload.get("quality"):
            payload["quality"] = build_quality_summary(payload.get("slides", []))
        payload.setdefault("lecture_goal", "standard")
        payload.setdefault("page_plan_preview", {})
        payload.setdefault("questions", [])
        payload.setdefault("exam_summary", build_exam_summary(payload.get("questions", [])))
        payload.setdefault("exam_settings", _parse_exam_settings(payload, payload.get("pdf_name", "")))
        payload.setdefault("agent_trace", build_initial_agent_trace())
        payload.setdefault("curriculum", {})
        payload.setdefault("pm_summary", {})
        payload.setdefault("artifacts", {})
        return jsonify(payload)
    except Exception as exc:
        error_id = _record_exception("api_slides", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/review-slides", methods=["POST"])
def api_review_slides():
    body = request.get_json()
    if not body:
        return jsonify({"error": "데이터 없음"}), 400

    slides_data = body.get("slides", [])
    if not isinstance(slides_data, list) or not slides_data:
        return jsonify({"error": "슬라이드 데이터 없음"}), 400

    assets = body.get("assets", [])
    page_plan = body.get("page_plan", {})
    page_plan_preview = body.get("page_plan_preview", {})
    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        return jsonify(
            {
                "ok": True,
                "slides": prepared["slides"],
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "page_plan_preview": page_plan_preview,
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_review_slides", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/slides/<uid>/update", methods=["POST"])
def api_update_slides(uid):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid uid"}), 400

    payload = _load_saved_payload(uid)
    if not payload:
        return jsonify({"error": "not found"}), 404

    body = request.get_json()
    if not body:
        return jsonify({"error": "데이터 없음"}), 400

    slides_data = body.get("slides", payload.get("slides", []))
    if not isinstance(slides_data, list) or not slides_data:
        return jsonify({"error": "슬라이드 데이터 없음"}), 400

    design = body.get("design", payload.get("design") or {"preset": "corporate"})
    assets = body.get("assets", payload.get("assets", []))
    page_plan = body.get("page_plan", payload.get("page_plan", {}))
    page_plan_preview = body.get("page_plan_preview", payload.get("page_plan_preview", {}))
    lecture_goal = body.get("lecture_goal", payload.get("lecture_goal", "standard"))
    pdf_name = body.get("pdf_name", payload.get("pdf_name", "강의교안"))
    questions = body.get("questions", payload.get("questions", []))
    exam_summary = body.get("exam_summary", payload.get("exam_summary") or build_exam_summary(questions))
    exam_settings = _parse_exam_settings(body, pdf_name)
    if "exam_enabled" not in body and payload.get("exam_settings"):
        exam_settings = payload.get("exam_settings")
    agent_trace = body.get("agent_trace", payload.get("agent_trace") or build_initial_agent_trace())
    curriculum = body.get("curriculum", payload.get("curriculum", {}))
    pm_summary = body.get("pm_summary", payload.get("pm_summary", {}))

    download_name = _sanitize_download_name(
        body.get("download_name"),
        payload.get("download_name") or _default_download_name(pdf_name),
    )

    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        prepared_slides = prepared["slides"]
        artifacts = dict(payload.get("artifacts") or {})
        artifacts["ppt"] = _persist_ppt_artifact(uid, prepared_slides, design, assets)
        final_trace = _with_formatter_state(agent_trace, "슬라이드 수정 후 PPT를 다시 생성했습니다.")
        updated_payload = {
            **payload,
            "slides": prepared_slides,
            "outline": prepared["outline"],
            "quality": prepared["quality"],
            "design": design,
            "assets": assets,
            "page_plan": page_plan,
            "page_plan_preview": page_plan_preview,
            "lecture_goal": lecture_goal,
            "pdf_name": pdf_name,
            "download_name": download_name,
            "questions": questions,
            "exam_summary": exam_summary,
            "exam_settings": exam_settings,
            "agent_trace": final_trace,
            "curriculum": curriculum,
            "pm_summary": pm_summary,
            "artifacts": artifacts,
        }
        _save_saved_payload(uid, updated_payload)
        return jsonify(
            {
                "ok": True,
                "preview_uid": uid,
                "slide_count": len(prepared_slides),
                "download_name": download_name,
                "slides": prepared_slides,
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "page_plan": page_plan,
                "page_plan_preview": page_plan_preview,
                "lecture_goal": lecture_goal,
                "questions": questions,
                "exam_summary": exam_summary,
                "exam_settings": exam_settings,
                "agent_trace": final_trace,
                **_artifact_response_fields(uid, artifacts),
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_update_slides", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/slides/<uid>/<int:slide_index>/variants", methods=["POST"])
def api_slide_variants(uid, slide_index):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid uid"}), 400

    payload = _load_saved_payload(uid)
    if not payload:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(silent=True) or {}
    slides = body.get("slides", payload.get("slides", []))
    if slide_index < 0 or slide_index >= len(slides):
        return jsonify({"error": "invalid slide index"}), 400

    design = body.get("design", payload.get("design") or {"preset": "corporate"})
    assets = body.get("assets", payload.get("assets", []))
    page_plan = body.get("page_plan", payload.get("page_plan", {}))
    try:
        variant_count = int(body.get("variant_count", 3) or 3)
    except (TypeError, ValueError):
        variant_count = 3
    variant_count = max(1, min(3, variant_count))

    try:
        variants = generate_slide_variants(
            slides,
            slide_index,
            design,
            assets,
            selected_pages=page_plan.get("selected_pages"),
            variant_count=variant_count,
        )
        return jsonify({"ok": True, "variants": variants})
    except Exception as exc:
        error_id = _record_exception("api_slide_variants", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/slides/<uid>/<int:slide_index>/apply-variant", methods=["POST"])
def api_apply_slide_variant(uid, slide_index):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid uid"}), 400

    payload = _load_saved_payload(uid)
    if not payload:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(silent=True) or {}
    slides = body.get("slides", payload.get("slides", []))
    if slide_index < 0 or slide_index >= len(slides):
        return jsonify({"error": "invalid slide index"}), 400

    variant_slide = body.get("slide")
    if not isinstance(variant_slide, dict):
        return jsonify({"error": "variant slide missing"}), 400

    design = body.get("design", payload.get("design") or {"preset": "corporate"})
    assets = body.get("assets", payload.get("assets", []))
    page_plan = body.get("page_plan", payload.get("page_plan", {}))
    page_plan_preview = body.get("page_plan_preview", payload.get("page_plan_preview", {}))
    lecture_goal = body.get("lecture_goal", payload.get("lecture_goal", "standard"))
    pdf_name = body.get("pdf_name", payload.get("pdf_name", "강의교안"))
    questions = body.get("questions", payload.get("questions", []))
    exam_summary = body.get("exam_summary", payload.get("exam_summary") or build_exam_summary(questions))
    exam_settings = _parse_exam_settings(body, pdf_name)
    if "exam_enabled" not in body and payload.get("exam_settings"):
        exam_settings = payload.get("exam_settings")
    agent_trace = body.get("agent_trace", payload.get("agent_trace") or build_initial_agent_trace())
    curriculum = body.get("curriculum", payload.get("curriculum", {}))
    pm_summary = body.get("pm_summary", payload.get("pm_summary", {}))
    download_name = _sanitize_download_name(
        body.get("download_name"),
        payload.get("download_name") or _default_download_name(pdf_name),
    )

    try:
        next_slides = list(slides)
        next_slides[slide_index] = variant_slide
        prepared = _prepare_slide_package(next_slides, assets, selected_pages=page_plan.get("selected_pages"))
        artifacts = dict(payload.get("artifacts") or {})
        artifacts["ppt"] = _persist_ppt_artifact(uid, prepared["slides"], design, assets)
        final_trace = _with_formatter_state(agent_trace, "시안 적용 후 PPT를 다시 생성했습니다.")
        updated_payload = {
            **payload,
            "slides": prepared["slides"],
            "outline": prepared["outline"],
            "quality": prepared["quality"],
            "design": design,
            "assets": assets,
            "page_plan": page_plan,
            "page_plan_preview": page_plan_preview,
            "lecture_goal": lecture_goal,
            "pdf_name": pdf_name,
            "download_name": download_name,
            "questions": questions,
            "exam_summary": exam_summary,
            "exam_settings": exam_settings,
            "agent_trace": final_trace,
            "curriculum": curriculum,
            "pm_summary": pm_summary,
            "artifacts": artifacts,
        }
        _save_saved_payload(uid, updated_payload)
        return jsonify(
            {
                "ok": True,
                "preview_uid": uid,
                "slides": prepared["slides"],
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "download_name": download_name,
                "page_plan": page_plan,
                "page_plan_preview": page_plan_preview,
                "lecture_goal": lecture_goal,
                "questions": questions,
                "exam_summary": exam_summary,
                "exam_settings": exam_settings,
                "agent_trace": final_trace,
                **_artifact_response_fields(uid, artifacts),
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_apply_slide_variant", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


@app.route("/api/health", methods=["GET"])
def api_health():
    return _json_response(
        {
            "ok": True,
            "service": "Teach-On",
            "time": datetime.utcnow().isoformat() + "Z",
            "ocr_available": OCR_AVAILABLE,
            "max_upload_mb": config.MAX_UPLOAD_MB,
            "dashboard_auth_enabled": _dashboard_auth_enabled(),
        }
    )


@app.route("/api/dashboard/auth/status", methods=["GET"])
def api_dashboard_auth_status():
    return _json_response(
        {
            **_dashboard_auth_state(),
            "token_enabled": bool(config.ADMIN_TOKEN),
            "password_enabled": bool(config.ADMIN_PASSWORD or config.ADMIN_PASSWORD_HASH),
        }
    )


@app.route("/api/dashboard/auth/login", methods=["POST"])
def api_dashboard_auth_login():
    if not _dashboard_auth_enabled():
        session["teachon_admin_authenticated"] = True
        session["teachon_admin_username"] = config.ADMIN_USERNAME
        return _json_response({"ok": True, **_dashboard_auth_state()})

    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not verify_admin_credentials(username, password):
        return _json_response(
            {
                "error": "관리자 계정 정보가 올바르지 않습니다.",
                "code": "dashboard_login_failed",
            },
            status=401,
        )

    session["teachon_admin_authenticated"] = True
    session["teachon_admin_username"] = username or config.ADMIN_USERNAME
    session["teachon_admin_authenticated_at"] = datetime.utcnow().isoformat() + "Z"
    return _json_response({"ok": True, **_dashboard_auth_state()})


@app.route("/api/dashboard/auth/logout", methods=["POST"])
def api_dashboard_auth_logout():
    session.pop("teachon_admin_authenticated", None)
    session.pop("teachon_admin_username", None)
    session.pop("teachon_admin_authenticated_at", None)
    return _json_response({"ok": True, **_dashboard_auth_state()})


@app.route("/api/dashboard/overview", methods=["GET"])
def api_dashboard_overview():
    guard = _dashboard_guard()
    if guard:
        return guard
    return _json_response(dashboard_overview())


@app.route("/api/dashboard/jobs", methods=["GET"])
def api_dashboard_jobs():
    guard = _dashboard_guard()
    if guard:
        return guard
    try:
        output_limit = max(1, min(100, int(request.args.get("output_limit", 20) or 20)))
        job_limit = max(1, min(100, int(request.args.get("job_limit", 20) or 20)))
    except (TypeError, ValueError):
        output_limit, job_limit = 20, 20
    return _json_response(dashboard_jobs(output_limit, job_limit))


@app.route("/api/dashboard/jobs/<job_or_uid>", methods=["GET"])
def api_dashboard_job_detail(job_or_uid):
    guard = _dashboard_guard()
    if guard:
        return guard
    detail = dashboard_job_detail(job_or_uid)
    if not detail:
        return _json_response({"error": "작업을 찾을 수 없습니다."}, status=404)
    return _json_response(detail)


@app.route("/api/dashboard/security", methods=["GET"])
def api_dashboard_security():
    guard = _dashboard_guard()
    if guard:
        return guard
    return _json_response(security_summary())


@app.route("/api/dashboard/connectors", methods=["GET", "POST"])
def api_dashboard_connectors():
    guard = _dashboard_guard(mutate=request.method != "GET")
    if guard:
        return guard
    if request.method == "GET":
        return _json_response({"connectors": [_ for _ in map(dict, load_connectors())]})

    body = request.get_json(silent=True) or {}
    connector = upsert_connector(body)
    return _json_response({"ok": True, "connector": connector})


@app.route("/api/dashboard/connectors/<connector_id>/test", methods=["POST"])
def api_dashboard_connector_test(connector_id):
    guard = _dashboard_guard(mutate=True)
    if guard:
        return guard
    result = test_connector(connector_id)
    status = 200 if result.get("ok") else 400
    return _json_response(result, status=status)


@app.route("/api/dashboard/connectors/<connector_id>/invoke", methods=["POST"])
def api_dashboard_connector_invoke(connector_id):
    guard = _dashboard_guard(mutate=True)
    if guard:
        return guard
    connector = get_connector(connector_id)
    if not connector:
        return _json_response({"error": "커넥터를 찾을 수 없습니다."}, status=404)
    body = request.get_json(silent=True) or {}
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    result = invoke_connector(connector_id, payload=payload)
    status = 200 if result.get("ok") else 400
    return _json_response(result, status=status)


@app.route("/api/dashboard/agent-tasks", methods=["GET", "POST"])
def api_dashboard_agent_tasks():
    guard = _dashboard_guard(mutate=request.method != "GET")
    if guard:
        return guard

    if request.method == "GET":
        try:
            limit = max(1, min(100, int(request.args.get("limit", 25) or 25)))
        except (TypeError, ValueError):
            limit = 25
        return _json_response({"agents": available_agents(), "tasks": list_agent_tasks(limit)})

    body = request.get_json(silent=True) or {}
    async_mode = str(body.get("async", "false")).strip().lower() in {"1", "true", "yes", "on"}
    try:
        task = _create_and_run_agent_task(body, async_mode=async_mode)
        return _json_response({"ok": True, "task": task})
    except Exception as exc:
        return _json_response({"error": str(exc)}, status=400)


@app.route("/api/dashboard/agent-tasks/<task_id>", methods=["GET"])
def api_dashboard_agent_task_detail(task_id):
    guard = _dashboard_guard()
    if guard:
        return guard
    task = get_agent_task(task_id)
    if not task:
        return _json_response({"error": "에이전트 작업을 찾을 수 없습니다."}, status=404)
    return _json_response({"task": task})


@app.route("/api/dashboard/slack/status", methods=["GET"])
def api_dashboard_slack_status():
    guard = _dashboard_guard()
    if guard:
        return guard
    return _json_response(slack_status())


@app.route("/api/dashboard/slack/test-post", methods=["POST"])
def api_dashboard_slack_test_post():
    guard = _dashboard_guard(mutate=True)
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    channel = str(body.get("channel") or config.SLACK_DEFAULT_CHANNEL or "").strip()
    text = str(body.get("text") or "Teach-On Dashboard에서 Slack 연결 테스트를 보냈습니다.").strip()
    result = slack_post_message(channel, text)
    status = 200 if result.get("ok") else 400
    return _json_response(result, status=status)


@app.route("/api/dashboard/telegram/status", methods=["GET"])
def api_dashboard_telegram_status():
    guard = _dashboard_guard()
    if guard:
        return guard
    return _json_response(telegram_status())


@app.route("/api/dashboard/telegram/test-post", methods=["POST"])
def api_dashboard_telegram_test_post():
    guard = _dashboard_guard(mutate=True)
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    chat_id = str(body.get("chat_id") or config.TELEGRAM_DEFAULT_CHAT_ID or "").strip()
    text = str(body.get("text") or "Teach-On Dashboard에서 Telegram 연결 테스트를 보냈습니다.").strip()
    result = telegram_send_message(chat_id, text)
    status = 200 if result.get("ok") else 400
    return _json_response(result, status=status)


@app.route("/slack/commands", methods=["POST"])
def slack_commands():
    if not config.SLACK_EVENTS_ENABLED:
        return _slack_json_response({"response_type": "ephemeral", "text": "Slack 연동이 비활성화되어 있습니다."}, status=403)

    ok, message = verify_slack_request(request)
    if not ok:
        return _slack_json_response({"response_type": "ephemeral", "text": f"Slack 요청 검증 실패: {message}"}, status=401)

    form = parse_qs(request.get_data(cache=True, as_text=True), keep_blank_values=True)
    text = (form.get("text") or [""])[0]
    channel_id = (form.get("channel_id") or [""])[0]
    response_url = (form.get("response_url") or [""])[0]
    record_slack_activity("slash_command", {"text": text, "channel_id": channel_id})
    reply_text, response_type = _handle_slack_command(
        text,
        channel_id=channel_id,
        response_url=response_url,
    )
    return _slack_json_response({"response_type": response_type, "text": reply_text})


@app.route("/slack/events", methods=["POST"])
def slack_events():
    payload = request.get_json(silent=True) or {}
    if payload.get("type") == "url_verification":
        record_slack_activity("url_verification", {"host": request.host})
        return _json_response({"challenge": payload.get("challenge", "")})

    if not config.SLACK_EVENTS_ENABLED:
        return _json_response({"ok": False, "error": "slack disabled"}, status=403)

    ok, message = verify_slack_request(request)
    if not ok:
        return _json_response({"ok": False, "error": message}, status=401)

    if payload.get("type") != "event_callback":
        return _json_response({"ok": True})

    event = payload.get("event") or {}
    event_type = str(event.get("type") or "").strip().lower()
    if event_type not in {"app_mention", "message"}:
        return _json_response({"ok": True})
    if event.get("bot_id"):
        return _json_response({"ok": True})

    text = strip_bot_mention(event.get("text") or "")
    channel_id = str(event.get("channel") or "").strip()
    thread_ts = str(event.get("thread_ts") or event.get("ts") or "").strip()
    record_slack_activity("event", {"type": event_type, "channel_id": channel_id, "text": text})

    def _respond():
        reply_text, _ = _handle_slack_command(text, channel_id=channel_id, thread_ts=thread_ts)
        if channel_id:
            slack_post_message(channel_id, reply_text, thread_ts=thread_ts)

    threading.Thread(target=_respond, daemon=True).start()
    return _json_response({"ok": True})


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    if not config.TELEGRAM_WEBHOOK_ENABLED:
        return _json_response({"ok": False, "error": "telegram disabled"}, status=403)

    ok, message = verify_telegram_request(request)
    if not ok:
        return _json_response({"ok": False, "error": message}, status=401)

    payload = request.get_json(silent=True) or {}
    context = telegram_extract_update_context(payload)
    if not context:
        record_telegram_activity("ignored_update", {"update_id": payload.get("update_id")})
        return _json_response({"ok": True, "ignored": True})

    chat_id = str(context.get("chat_id") or "").strip()
    callback_query_id = str(context.get("callback_query_id") or "").strip()
    if context.get("is_bot"):
        return _json_response({"ok": True, "ignored": True})
    if not telegram_is_allowed_chat(chat_id):
        record_telegram_activity(
            "rejected_chat",
            {
                "chat_id": chat_id,
                "kind": context.get("kind"),
                "message_id": context.get("message_id"),
            },
        )
        if callback_query_id:
            telegram_answer_callback_query(callback_query_id, text="허용되지 않은 채팅입니다.", show_alert=True)
        return _json_response({"ok": True, "ignored": True})

    record_telegram_activity(
        "update",
        {
            "kind": context.get("kind"),
            "chat_id": chat_id,
            "message_id": context.get("message_id"),
            "username": context.get("username"),
            "text": str(context.get("text") or "")[:240],
        },
    )
    telegram_record_thread_context(
        chat_id,
        context.get("message_id"),
        "user",
        str(context.get("text") or ""),
        metadata={
            "kind": context.get("kind"),
            "username": context.get("username"),
        },
    )

    def _respond():
        try:
            result = handle_telegram_pm_message(
                str(context.get("text") or ""),
                chat_id=chat_id,
                message_id=context.get("message_id"),
                username=str(context.get("username") or ""),
                display_name=str(context.get("display_name") or ""),
                on_complete=_post_agent_task_result_to_telegram,
            )
            reply_text = str(result.get("reply_text") or "").strip()
            if reply_text and chat_id:
                telegram_send_message(
                    chat_id,
                    reply_text,
                    reply_to_message_id=context.get("message_id"),
                )
                telegram_record_thread_context(
                    chat_id,
                    context.get("message_id"),
                    "assistant",
                    reply_text,
                    metadata={"kind": "reply"},
                )
            if callback_query_id:
                telegram_answer_callback_query(
                    callback_query_id,
                    text=str(result.get("callback_text") or "처리했습니다."),
                )
        except Exception as exc:
            error_text = _safe_error_text(exc)
            record_telegram_activity(
                "handler_error",
                {
                    "chat_id": chat_id,
                    "message_id": context.get("message_id"),
                    "error": error_text,
                },
            )
            if chat_id:
                telegram_send_message(chat_id, f"Telegram 처리 중 오류가 발생했습니다: {error_text}")
                telegram_record_thread_context(
                    chat_id,
                    context.get("message_id"),
                    "assistant",
                    f"Telegram 처리 중 오류가 발생했습니다: {error_text}",
                    metadata={"kind": "error"},
                )
            if callback_query_id:
                telegram_answer_callback_query(callback_query_id, text="처리 중 오류가 발생했습니다.", show_alert=True)

    threading.Thread(target=_respond, daemon=True).start()
    return _json_response({"ok": True})


@app.route("/api/history", methods=["GET"])
def api_history():
    return jsonify(get_history())


@app.route("/download/<uid>")
def download(uid):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid"}), 400
    payload = _load_saved_payload(uid)
    if not payload:
        return jsonify({"error": "not found"}), 404

    ppt_meta = (payload.get("artifacts") or {}).get("ppt") or {}
    path = ppt_meta.get("path")
    if not path or not os.path.exists(path):
        try:
            path = _persist_ppt_artifact(
                uid,
                payload.get("slides", []),
                payload.get("design") or {"preset": "corporate"},
                payload.get("assets", []),
            )["path"]
        except Exception as exc:
            error_id = _record_exception("download_generate_pptx", exc)
            return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500

    download_name = _artifact_download_name(payload, "ppt", request.args.get("name"))
    return send_file(
        path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.route("/download/<uid>/<artifact_kind>")
def download_artifact(uid, artifact_kind):
    if not UID_RE.match(uid):
        return jsonify({"error": "invalid"}), 400
    if artifact_kind not in {"exam", "answer", "exam_a", "exam_b"}:
        return jsonify({"error": "unsupported artifact"}), 400

    payload = _load_saved_payload(uid)
    if not payload:
        return jsonify({"error": "not found"}), 404

    artifacts = payload.get("artifacts") or {}
    meta = artifacts.get(artifact_kind) or {}
    path = meta.get("path")
    if not path or not os.path.exists(path):
        questions = payload.get("questions", [])
        exam_settings = payload.get("exam_settings") or _parse_exam_settings(payload, payload.get("pdf_name", ""))
        try:
            regenerated = _persist_exam_artifacts(uid, questions, exam_settings)
            artifacts.update(regenerated)
            payload["artifacts"] = artifacts
            _save_saved_payload(uid, payload)
            meta = artifacts.get(artifact_kind) or {}
            path = meta.get("path")
        except Exception as exc:
            error_id = _record_exception("download_generate_docx", exc)
            return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500

    if not path or not os.path.exists(path):
        return jsonify({"error": "artifact not found"}), 404

    return send_file(
        path,
        as_attachment=True,
        download_name=_artifact_download_name(payload, artifact_kind, request.args.get("name")),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5050))
    print(f"\n✅  http://localhost:{port}  에서 실행 중\n")
    app.run(host="0.0.0.0", port=port, debug=False)
