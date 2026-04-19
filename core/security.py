from __future__ import annotations

import hashlib
import hmac
import ipaddress
import threading
import time
from collections import defaultdict, deque
from typing import Any

from werkzeug.security import check_password_hash

import config


RATE_LIMIT_BUCKETS = {
    "dashboard_login": {"limit": 6, "window": 300},
    "dashboard_mutation": {"limit": 30, "window": 60},
    "heavy_job": {"limit": 10, "window": 600},
    "default_api": {"limit": 180, "window": 60},
    "page": {"limit": 240, "window": 60},
}

_RATE_LIMIT_STATE: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_RATE_LIMIT_LOCK = threading.Lock()


def _parse_networks(raw: str | None) -> list[ipaddress._BaseNetwork]:
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    networks: list[ipaddress._BaseNetwork] = []
    for value in values:
        try:
            if "/" in value:
                networks.append(ipaddress.ip_network(value, strict=False))
            else:
                addr = ipaddress.ip_address(value)
                prefix = 32 if addr.version == 4 else 128
                networks.append(ipaddress.ip_network(f"{value}/{prefix}", strict=False))
        except ValueError:
            continue
    return networks


def dashboard_allowlist_networks() -> list[ipaddress._BaseNetwork]:
    return _parse_networks(config.DASHBOARD_IP_ALLOWLIST)


def resolve_client_ip(flask_request) -> str:
    forwarded = str(flask_request.headers.get("X-Forwarded-For", "")).strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = str(flask_request.headers.get("X-Real-IP", "")).strip()
    if real_ip:
        return real_ip
    return str(flask_request.remote_addr or "127.0.0.1").strip()


def is_ip_allowed(ip_text: str, networks: list[ipaddress._BaseNetwork] | None = None) -> bool:
    rules = dashboard_allowlist_networks() if networks is None else networks
    if not rules:
        return True
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(address in network for network in rules)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_admin_credentials(username: str, password: str) -> bool:
    expected_user = str(config.ADMIN_USERNAME or "admin").strip()
    if not expected_user:
        return False
    if not hmac.compare_digest(str(username or ""), expected_user):
        return False

    raw_hash = str(config.ADMIN_PASSWORD_HASH or "").strip()
    raw_password = str(config.ADMIN_PASSWORD or "").strip()
    provided_password = str(password or "")

    if raw_hash:
        if raw_hash.startswith("pbkdf2:") or raw_hash.startswith("scrypt:"):
            try:
                return check_password_hash(raw_hash, provided_password)
            except Exception:
                return False
        return hmac.compare_digest(_sha256_hex(provided_password), raw_hash.lower())

    if raw_password:
        return hmac.compare_digest(provided_password, raw_password)

    return False


def rate_limit_bucket_for_request(path: str, method: str) -> str:
    normalized = str(path or "")
    verb = str(method or "GET").upper()
    if normalized == "/api/dashboard/auth/login":
        return "dashboard_login"
    if normalized.startswith("/api/dashboard") and verb in {"POST", "PUT", "PATCH", "DELETE"}:
        return "dashboard_mutation"
    if normalized.startswith("/api/analyze") or normalized.startswith("/api/generate"):
        return "heavy_job"
    if normalized.startswith("/api/"):
        return "default_api"
    return "page"


def rate_limit_settings(bucket: str) -> dict[str, int]:
    return RATE_LIMIT_BUCKETS.get(bucket, RATE_LIMIT_BUCKETS["default_api"])


def check_rate_limit(client_ip: str, bucket: str, now: float | None = None) -> tuple[bool, int, dict[str, int]]:
    ts = time.time() if now is None else now
    config_row = rate_limit_settings(bucket)
    limit = int(config_row["limit"])
    window = int(config_row["window"])
    key = (client_ip, bucket)

    with _RATE_LIMIT_LOCK:
        queue = _RATE_LIMIT_STATE[key]
        while queue and (ts - queue[0]) > window:
            queue.popleft()
        if len(queue) >= limit:
            retry_after = max(1, int(window - (ts - queue[0])))
            return False, retry_after, config_row
        queue.append(ts)
        return True, 0, config_row


def rate_limit_summary() -> list[dict[str, Any]]:
    return [
        {"bucket": key, "limit": value["limit"], "window_seconds": value["window"]}
        for key, value in RATE_LIMIT_BUCKETS.items()
    ]
