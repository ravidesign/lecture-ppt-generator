from __future__ import annotations

import json
import re
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import config

try:
    import certifi
except Exception:  # pragma: no cover - optional dependency at runtime
    certifi = None


FIGMA_API_BASE_URL = "https://api.figma.com"
FIGMA_URL_TYPES = {"file", "design", "proto", "board", "slides"}
SAFE_FIGMA_KEY = re.compile(r"^[A-Za-z0-9_-]{8,}$")


class FigmaAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def figma_access_token() -> str:
    token = config.FIGMA_ACCESS_TOKEN.strip()
    if not token:
        raise FigmaAPIError("FIGMA_ACCESS_TOKEN is 비어 있습니다. .env에 먼저 설정해 주세요.")
    return token


def extract_file_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if SAFE_FIGMA_KEY.fullmatch(text) and "://" not in text and "/" not in text:
        return text

    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc or "figma.com" not in parsed.netloc.lower():
        return ""

    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part in FIGMA_URL_TYPES:
            candidate = parts[index + 1]
            return candidate if SAFE_FIGMA_KEY.fullmatch(candidate) else ""
    return ""


def _figma_headers(token: str | None = None) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "Teach-On-Figma/1.0",
        "X-Figma-Token": (token or figma_access_token()).strip(),
    }


def _ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        try:
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
    return ssl.create_default_context()


def _decode_response_body(raw_bytes: bytes) -> Any:
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _error_message_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "err", "error", "status"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def request_json(
    path: str,
    *,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout_seconds: int = 12,
) -> Any:
    query_string = ""
    if query:
        normalized = {
            key: value
            for key, value in query.items()
            if value is not None and str(value).strip() != ""
        }
        if normalized:
            query_string = "?" + urlencode(normalized, doseq=True)

    data = None
    headers = _figma_headers(token)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    url = f"{FIGMA_API_BASE_URL}{path}{query_string}"
    request = Request(url, data=data, method=method.upper(), headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds, context=_ssl_context()) as response:
            return _decode_response_body(response.read())
    except HTTPError as exc:
        error_payload = _decode_response_body(exc.read())
        message = _error_message_from_payload(error_payload) or exc.reason or "Figma API 요청에 실패했습니다."
        raise FigmaAPIError(message, status_code=exc.code, payload=error_payload) from exc
    except URLError as exc:
        raise FigmaAPIError(str(exc.reason or exc)) from exc
    except Exception as exc:
        raise FigmaAPIError(str(exc)) from exc


def get_current_user(*, timeout_seconds: int = 12) -> dict[str, Any]:
    response = request_json("/v1/me", timeout_seconds=timeout_seconds)
    return response if isinstance(response, dict) else {"raw": response}


def get_file_document(file_key_or_url: str, *, depth: int | None = 1, timeout_seconds: int = 20) -> dict[str, Any]:
    file_key = extract_file_key(file_key_or_url)
    if not file_key:
        raise FigmaAPIError("유효한 Figma file key 또는 파일 URL이 필요합니다.")
    query = {"depth": depth} if depth is not None else None
    response = request_json(f"/v1/files/{quote(file_key, safe='')}", query=query, timeout_seconds=timeout_seconds)
    return response if isinstance(response, dict) else {"raw": response}


def get_file_metadata(file_key_or_url: str, *, timeout_seconds: int = 12) -> dict[str, Any]:
    file_key = extract_file_key(file_key_or_url)
    if not file_key:
        raise FigmaAPIError("유효한 Figma file key 또는 파일 URL이 필요합니다.")
    response = request_json(f"/v1/files/{quote(file_key, safe='')}/meta", timeout_seconds=timeout_seconds)
    return response if isinstance(response, dict) else {"raw": response}
