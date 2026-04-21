from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from core.dashboard_service import test_connector, upsert_connector
from core.figma_client import (
    FigmaAPIError,
    extract_file_key,
    get_current_user,
    get_file_document,
    get_file_metadata,
)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _current_user_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "email": payload.get("email"),
        "handle": payload.get("handle"),
        "img_url": payload.get("img_url"),
    }


def _file_document_summary(payload: dict[str, Any], file_key: str) -> dict[str, Any]:
    document = payload.get("document") or {}
    pages = document.get("children") if isinstance(document, dict) else []
    page_names = []
    if isinstance(pages, list):
        for page in pages[:10]:
            if isinstance(page, dict):
                name = str(page.get("name") or "").strip()
                if name:
                    page_names.append(name)
    return {
        "file_key": file_key,
        "name": payload.get("name"),
        "editor_type": payload.get("editorType"),
        "last_modified": payload.get("lastModified"),
        "thumbnail_url": payload.get("thumbnailUrl"),
        "page_count": len(pages) if isinstance(pages, list) else 0,
        "pages_preview": page_names,
    }


def _file_metadata_summary(payload: dict[str, Any], file_key: str) -> dict[str, Any]:
    meta = payload.get("file") or {}
    return {
        "file_key": file_key,
        "name": meta.get("name"),
        "folder_name": meta.get("folder_name"),
        "last_touched_at": meta.get("last_touched_at"),
        "editor_type": meta.get("editorType"),
        "role": meta.get("role"),
        "url": meta.get("url"),
    }


def _register_connector(test_after_save: bool) -> int:
    connector = upsert_connector(
        {
            "id": "figma-api",
            "name": "Figma API",
            "type": "agent_api",
            "base_url": "https://api.figma.com",
            "health_url": "https://api.figma.com/v1/me",
            "trigger_url": "",
            "auth_type": "x_figma_token_env",
            "api_key_env": "FIGMA_ACCESS_TOKEN",
            "capabilities": ["figma_api", "current_user_read"],
            "description": "Teach-On 로컬 FIGMA_ACCESS_TOKEN으로 Figma REST API 연결 상태를 점검합니다.",
            "enabled": True,
        }
    )
    result: dict[str, Any] = {"ok": True, "connector": connector}
    if test_after_save:
        result["test"] = test_connector(connector["id"])
    _print_json(result)
    return 0 if (not test_after_save or result["test"].get("ok")) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Teach-On Figma REST API helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("me", help="현재 Figma 사용자 정보를 확인합니다.")

    file_parser = subparsers.add_parser("file", help="Figma 파일 기본 정보를 가져옵니다.")
    file_parser.add_argument("file_key_or_url", help="Figma file key 또는 파일 URL")
    file_parser.add_argument("--depth", type=int, default=1, help="문서 트리 depth (기본값: 1)")

    file_meta_parser = subparsers.add_parser("file-meta", help="Figma 파일 메타데이터를 가져옵니다.")
    file_meta_parser.add_argument("file_key_or_url", help="Figma file key 또는 파일 URL")

    key_parser = subparsers.add_parser("extract-key", help="Figma URL에서 file key만 추출합니다.")
    key_parser.add_argument("file_key_or_url", help="Figma file key 또는 파일 URL")

    connector_parser = subparsers.add_parser("register-connector", help="대시보드 Figma 커넥터를 저장합니다.")
    connector_parser.add_argument("--test", action="store_true", help="저장 직후 /v1/me 연결 점검도 수행합니다.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "me":
            _print_json(_current_user_summary(get_current_user()))
            return 0
        if args.command == "file":
            file_key = extract_file_key(args.file_key_or_url)
            payload = get_file_document(args.file_key_or_url, depth=args.depth)
            _print_json(_file_document_summary(payload, file_key))
            return 0
        if args.command == "file-meta":
            file_key = extract_file_key(args.file_key_or_url)
            payload = get_file_metadata(args.file_key_or_url)
            _print_json(_file_metadata_summary(payload, file_key))
            return 0
        if args.command == "extract-key":
            file_key = extract_file_key(args.file_key_or_url)
            if not file_key:
                raise FigmaAPIError("file key를 추출할 수 없습니다.")
            print(file_key)
            return 0
        if args.command == "register-connector":
            return _register_connector(test_after_save=args.test)
    except FigmaAPIError as exc:
        payload = {"ok": False, "error": str(exc)}
        if exc.status_code is not None:
            payload["status_code"] = exc.status_code
        if exc.payload is not None:
            payload["details"] = exc.payload
        _print_json(payload)
        return 1

    parser.error("지원하지 않는 명령입니다.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
