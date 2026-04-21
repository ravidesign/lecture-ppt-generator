from __future__ import annotations

import json
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import config
from core.security import dashboard_allowlist_networks, rate_limit_summary

try:
    import certifi
except Exception:  # pragma: no cover - optional dependency at runtime
    certifi = None


SAFE_CONNECTOR_ID = re.compile(r"[^a-z0-9_-]+")
CONNECTOR_TYPES = {"webhook", "agent_api", "automation", "mcp_bridge"}
CONNECTOR_AUTH_TYPES = {"none", "bearer_env", "x_figma_token_env"}
ARTIFACT_SUFFIX_MAP = {
    "ppt": ".pptx",
    "exam": ".docx",
    "answer": ".docx",
    "exam_a": ".docx",
    "exam_b": ".docx",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug_connector_id(value: str) -> str:
    text = SAFE_CONNECTOR_ID.sub("-", str(value or "").strip().lower()).strip("-")
    return text[:64] or f"connector-{datetime.now().strftime('%H%M%S')}"


def _ensure_dashboard_storage() -> None:
    config.ensure_dirs()
    if not config.INTEGRATIONS_FILE.exists():
        _write_json(config.INTEGRATIONS_FILE, {"connectors": [], "updated_at": _iso_now()})


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


def _safe_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        try:
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
    return ssl.create_default_context()


def _connector_headers(connector: dict) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "User-Agent": "Teach-On-Dashboard/1.0",
    }
    auth_type = str(connector.get("auth_type") or "none").strip().lower()
    env_name = str(connector.get("api_key_env") or "").strip()
    if auth_type == "bearer_env" and env_name:
        token = os.getenv(env_name, "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if auth_type == "x_figma_token_env" and env_name:
        token = os.getenv(env_name, "").strip()
        if token:
            headers["X-Figma-Token"] = token
    return headers


def _connector_payload(connector: dict) -> dict:
    return {
        "id": connector["id"],
        "name": connector["name"],
        "type": connector["type"],
        "description": connector.get("description", ""),
        "base_url": connector.get("base_url", ""),
        "health_url": connector.get("health_url", ""),
        "trigger_url": connector.get("trigger_url", ""),
        "capabilities": connector.get("capabilities", []),
        "enabled": connector.get("enabled", True),
        "auth_type": connector.get("auth_type", "none"),
        "api_key_env": connector.get("api_key_env", ""),
        "last_health": connector.get("last_health"),
        "last_checked_at": connector.get("last_checked_at"),
        "last_invoked_at": connector.get("last_invoked_at"),
        "updated_at": connector.get("updated_at"),
        "created_at": connector.get("created_at"),
    }


def load_connectors() -> list[dict]:
    _ensure_dashboard_storage()
    payload = _read_json(config.INTEGRATIONS_FILE, {"connectors": []})
    return [connector for connector in payload.get("connectors", []) if isinstance(connector, dict)]


def save_connectors(connectors: list[dict]) -> None:
    _write_json(
        config.INTEGRATIONS_FILE,
        {"connectors": connectors, "updated_at": _iso_now()},
    )


def normalize_connector_payload(data: dict) -> dict:
    capabilities = data.get("capabilities", [])
    if isinstance(capabilities, str):
        capabilities = [item.strip() for item in capabilities.split(",") if item.strip()]
    capabilities = [str(item).strip() for item in capabilities if str(item).strip()]

    requested_type = str(data.get("type") or "webhook").strip().lower()
    connector_type = requested_type if requested_type in CONNECTOR_TYPES else "webhook"
    requested_auth_type = str(data.get("auth_type") or "none").strip().lower()
    auth_type = requested_auth_type if requested_auth_type in CONNECTOR_AUTH_TYPES else "none"
    name = str(data.get("name") or "").strip() or "새 커넥터"

    return {
        "id": _slug_connector_id(data.get("id") or name),
        "name": name,
        "type": connector_type,
        "description": str(data.get("description") or "").strip(),
        "base_url": _safe_url(data.get("base_url") or ""),
        "health_url": _safe_url(data.get("health_url") or ""),
        "trigger_url": _safe_url(data.get("trigger_url") or ""),
        "capabilities": capabilities,
        "enabled": _coerce_bool(data.get("enabled"), True),
        "auth_type": auth_type,
        "api_key_env": str(data.get("api_key_env") or "").strip(),
    }


def upsert_connector(data: dict) -> dict:
    connector = normalize_connector_payload(data)
    connectors = load_connectors()
    now = _iso_now()
    updated = False
    for index, existing in enumerate(connectors):
        if existing.get("id") != connector["id"]:
            continue
        connector["created_at"] = existing.get("created_at") or now
        connector["last_health"] = existing.get("last_health")
        connector["last_checked_at"] = existing.get("last_checked_at")
        connector["last_invoked_at"] = existing.get("last_invoked_at")
        connector["updated_at"] = now
        connectors[index] = connector
        updated = True
        break
    if not updated:
        connector["created_at"] = now
        connector["updated_at"] = now
        connector["last_health"] = None
        connector["last_checked_at"] = None
        connector["last_invoked_at"] = None
        connectors.append(connector)
    save_connectors(connectors)
    return _connector_payload(connector)


def get_connector(connector_id: str) -> dict | None:
    connector_id = _slug_connector_id(connector_id)
    for connector in load_connectors():
        if connector.get("id") == connector_id:
            return connector
    return None


def _update_connector_runtime_fields(connector_id: str, **changes) -> dict | None:
    connectors = load_connectors()
    target = None
    for connector in connectors:
        if connector.get("id") != connector_id:
            continue
        connector.update(changes)
        connector["updated_at"] = _iso_now()
        target = connector
        break
    if target is None:
        return None
    save_connectors(connectors)
    return target


def test_connector(connector_id: str, timeout_seconds: int = 8) -> dict:
    connector = get_connector(connector_id)
    if not connector:
        return {"ok": False, "error": "커넥터를 찾을 수 없습니다."}
    if not connector.get("enabled", True):
        return {"ok": False, "error": "비활성화된 커넥터입니다."}

    target_url = connector.get("health_url") or connector.get("base_url")
    if not target_url:
        return {"ok": False, "error": "health_url 또는 base_url이 필요합니다."}

    headers = _connector_headers(connector)
    request = Request(target_url, method="GET", headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as response:
            body = response.read(512).decode("utf-8", errors="replace")
            result = {
                "ok": True,
                "status_code": response.status,
                "response_preview": body.strip(),
                "checked_at": _iso_now(),
            }
    except HTTPError as exc:
        body = exc.read(512).decode("utf-8", errors="replace")
        result = {
            "ok": False,
            "status_code": exc.code,
            "error": body.strip() or exc.reason,
            "checked_at": _iso_now(),
        }
    except URLError as exc:
        result = {
            "ok": False,
            "error": str(exc.reason or exc),
            "checked_at": _iso_now(),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "checked_at": _iso_now(),
        }

    _update_connector_runtime_fields(
        connector["id"],
        last_health=result,
        last_checked_at=result["checked_at"],
    )
    return result


def invoke_connector(connector_id: str, payload: dict | None = None, timeout_seconds: int = 12) -> dict:
    connector = get_connector(connector_id)
    if not connector:
        return {"ok": False, "error": "커넥터를 찾을 수 없습니다."}
    if not connector.get("enabled", True):
        return {"ok": False, "error": "비활성화된 커넥터입니다."}

    target_url = connector.get("trigger_url") or connector.get("base_url")
    if not target_url:
        return {"ok": False, "error": "trigger_url 또는 base_url이 필요합니다."}

    body_bytes = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    headers = _connector_headers(connector)
    headers["Content-Type"] = "application/json"
    request = Request(target_url, data=body_bytes, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as response:
            body = response.read(1024).decode("utf-8", errors="replace")
            result = {
                "ok": True,
                "status_code": response.status,
                "response_preview": body.strip(),
                "invoked_at": _iso_now(),
            }
    except HTTPError as exc:
        body = exc.read(1024).decode("utf-8", errors="replace")
        result = {
            "ok": False,
            "status_code": exc.code,
            "error": body.strip() or exc.reason,
            "invoked_at": _iso_now(),
        }
    except URLError as exc:
        result = {
            "ok": False,
            "error": str(exc.reason or exc),
            "invoked_at": _iso_now(),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "invoked_at": _iso_now(),
        }

    _update_connector_runtime_fields(
        connector["id"],
        last_invoked_at=result["invoked_at"],
    )
    return result


def _load_saved_payloads(limit: int = 25) -> list[dict]:
    payloads: list[dict] = []
    for path in sorted(config.OUTPUTS_DIR.glob("*_slides.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        uid = path.name.split("_slides.json", 1)[0]
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue

        slides = payload.get("slides", []) or []
        questions = payload.get("questions", []) or []
        design = payload.get("design") or {}
        artifacts = payload.get("artifacts") or {}
        payloads.append(
            {
                "uid": uid,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "pdf_name": payload.get("pdf_name", ""),
                "download_name": payload.get("download_name", ""),
                "lecture_goal": payload.get("lecture_goal", "standard"),
                "slide_count": len(slides),
                "question_count": len(questions),
                "preset": design.get("preset", "corporate"),
                "artifacts": list(artifacts.keys()),
                "questions_enabled": bool(payload.get("exam_settings", {}).get("exam_enabled", True)),
                "agent_trace": payload.get("agent_trace", []),
                "preview_url": f"/preview/{uid}",
                "download_url": f"/download/{uid}",
            }
        )
        if len(payloads) >= limit:
            break
    return payloads


def _load_analyze_jobs(limit: int = 25) -> list[dict]:
    jobs: list[dict] = []
    if not config.ANALYZE_JOBS_DIR.exists():
        return jobs
    for path in sorted(config.ANALYZE_JOBS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        jobs.append(
            {
                "job_id": payload.get("job_id") or path.stem,
                "status": payload.get("status", "unknown"),
                "stage": payload.get("stage", ""),
                "message": payload.get("message", ""),
                "updated_at": payload.get("updated_at"),
                "created_at": payload.get("created_at"),
                "finished_at": payload.get("finished_at"),
                "agents": payload.get("agents", []),
                "error": payload.get("error"),
                "error_id": payload.get("error_id"),
            }
        )
        if len(jobs) >= limit:
            break
    return jobs


def _artifact_count(kind: str) -> int:
    suffix = ARTIFACT_SUFFIX_MAP.get(kind, "")
    if kind == "ppt":
        return len(list(config.PPTX_DIR.glob(f"*{suffix}")))
    return len(list(config.DOCX_DIR.glob(f"*_{kind}{suffix}")))


def security_summary() -> dict:
    auth_enabled = bool(config.ADMIN_TOKEN)
    password_auth_enabled = bool(config.ADMIN_PASSWORD or config.ADMIN_PASSWORD_HASH)
    allowlist = dashboard_allowlist_networks()
    return {
        "upload_limit_mb": config.MAX_UPLOAD_MB,
        "dashboard_token_enabled": auth_enabled,
        "dashboard_password_enabled": password_auth_enabled,
        "dashboard_ip_allowlist_count": len(allowlist),
        "dashboard_mutation_policy": "session_or_header_token" if (auth_enabled or password_auth_enabled) else "open_with_warning",
        "rate_limits": rate_limit_summary(),
        "ocr_enabled": True,
        "secure_headers": {
            "csp": True,
            "nosniff": True,
            "frame_options": True,
            "referrer_policy": True,
        },
        "findings": [
            {
                "level": "ok" if auth_enabled else "warn",
                "title": "대시보드 관리자 토큰",
                "message": "TEACHON_ADMIN_TOKEN이 설정되어 있습니다." if auth_enabled else "관리자 토큰이 비어 있어 대시보드 변경 작업이 공개 모드로 동작합니다.",
            },
            {
                "level": "ok" if password_auth_enabled else "warn",
                "title": "대시보드 로그인 자격증명",
                "message": "운영용 세션 로그인이 활성화되어 있습니다." if password_auth_enabled else "TEACHON_ADMIN_PASSWORD 또는 TEACHON_ADMIN_PASSWORD_HASH가 비어 있습니다.",
            },
            {
                "level": "ok" if allowlist else "warn",
                "title": "IP Allowlist",
                "message": f"대시보드 IP 허용 목록 {len(allowlist)}개가 적용되어 있습니다." if allowlist else "대시보드 IP 허용 목록이 비어 있어 모든 IP에서 접근 가능합니다.",
            },
            {
                "level": "ok",
                "title": "업로드 크기 제한",
                "message": f"최대 업로드 크기가 {config.MAX_UPLOAD_MB}MB로 제한됩니다.",
            },
            {
                "level": "ok",
                "title": "보안 헤더",
                "message": "CSP, nosniff, frame-ancestors, referrer-policy 헤더를 적용합니다.",
            },
            {
                "level": "ok",
                "title": "파일 저장 안정성",
                "message": "이력/대시보드 레지스트리/작업 상태는 원자적 저장으로 기록됩니다.",
            },
        ],
    }


def dashboard_overview() -> dict:
    outputs = _load_saved_payloads(limit=50)
    jobs = _load_analyze_jobs(limit=50)
    connectors = load_connectors()

    active_jobs = [job for job in jobs if job.get("status") in {"queued", "running"}]
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]
    completed_jobs = [job for job in jobs if job.get("status") == "completed"]
    average_slides = round(sum(item["slide_count"] for item in outputs) / len(outputs), 1) if outputs else 0
    average_questions = round(sum(item["question_count"] for item in outputs) / len(outputs), 1) if outputs else 0

    return {
        "generated_outputs": len(outputs),
        "active_jobs": len(active_jobs),
        "completed_jobs": len(completed_jobs),
        "failed_jobs": len(failed_jobs),
        "average_slides": average_slides,
        "average_questions": average_questions,
        "ppt_count": _artifact_count("ppt"),
        "exam_docx_count": _artifact_count("exam"),
        "answer_docx_count": _artifact_count("answer"),
        "connectors_enabled": sum(1 for item in connectors if item.get("enabled", True)),
        "connectors_total": len(connectors),
        "security": security_summary(),
        "system": {
            "python_version": sys.version.split()[0],
            "ocr_available": True,
            "last_scanned_at": _iso_now(),
        },
    }


def dashboard_jobs(limit_outputs: int = 20, limit_active: int = 20) -> dict:
    outputs = _load_saved_payloads(limit_outputs)
    jobs = _load_analyze_jobs(limit_active)
    return {
        "recent_outputs": outputs,
        "analyze_jobs": jobs,
    }


def dashboard_job_detail(job_or_uid: str) -> dict | None:
    safe = str(job_or_uid or "").strip()
    if not safe:
        return None

    payload_path = config.OUTPUTS_DIR / f"{safe}_slides.json"
    if payload_path.exists():
        payload = _read_json(payload_path, {})
        return {
            "kind": "output",
            "uid": safe,
            "pdf_name": payload.get("pdf_name", ""),
            "download_name": payload.get("download_name", ""),
            "lecture_goal": payload.get("lecture_goal", "standard"),
            "slides": payload.get("slides", []),
            "questions": payload.get("questions", []),
            "exam_summary": payload.get("exam_summary"),
            "exam_settings": payload.get("exam_settings", {}),
            "agent_trace": payload.get("agent_trace", []),
            "artifacts": payload.get("artifacts", {}),
            "curriculum": payload.get("curriculum", {}),
            "pm_summary": payload.get("pm_summary", {}),
            "preview_url": f"/preview/{safe}",
        }

    job_path = config.ANALYZE_JOBS_DIR / f"{safe}.json"
    if job_path.exists():
        payload = _read_json(job_path, {})
        return {
            "kind": "analyze_job",
            "job_id": safe,
            "status": payload.get("status", "unknown"),
            "stage": payload.get("stage", ""),
            "message": payload.get("message", ""),
            "agents": payload.get("agents", []),
            "error": payload.get("error"),
            "error_id": payload.get("error_id"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "finished_at": payload.get("finished_at"),
            "result": payload.get("result"),
        }

    return None
