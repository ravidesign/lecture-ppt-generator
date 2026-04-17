import io
import json
import logging
import os
import locale
import re
import shutil
import subprocess
import sys
import traceback
import uuid
from datetime import datetime

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

from core.claude_analyzer import analyze_pdf
from core.history import add_record, get_history
from core.pdf_parser import extract_pdf_images, parse_page_range, resolve_page_selection
from core.ppt_generator import (
    LEGACY_THEME_PRESET_MAP,
    PRESETS,
    SUPPORTED_FONTS,
    generate_pptx_bytes,
)
from core.slide_quality import build_outline, build_quality_summary, review_slides
from core.slide_enricher import attach_pdf_images_to_slides

app = Flask(__name__)
# Keep API JSON ASCII-safe so Render/gunicorn never has to emit raw Unicode
# while streaming large Korean slide payloads back to the browser.
app.config["JSON_AS_ASCII"] = True
app.json.ensure_ascii = True

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")
UID_RE = re.compile(r"^[a-f0-9]{8}$")
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
SAFE_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
ERROR_LOG_FILE = os.path.join(OUTPUT_DIR, "server_errors.log")
OCRMYPDF_BIN = shutil.which("ocrmypdf")
TESSERACT_BIN = shutil.which("tesseract")
OCR_AVAILABLE = bool(OCRMYPDF_BIN and TESSERACT_BIN)


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


_ensure_utf8_runtime()


@app.before_request
def _refresh_runtime_encoding():
    _ensure_utf8_runtime()


@app.after_request
def _disable_response_caching(response):
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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


def _prepare_slide_package(slides_data: list[dict], assets: list[dict] | None, selected_pages: list[int] | None = None):
    reviewed = review_slides(slides_data, selected_pages=selected_pages)
    prepared_slides = attach_pdf_images_to_slides(reviewed["slides"], assets)
    return {
        "slides": prepared_slides,
        "outline": build_outline(prepared_slides),
        "quality": build_quality_summary(prepared_slides),
    }


def _candidate_asset_pages(slides_data: list[dict], selected_pages: list[int] | None, radius: int = 1, max_pages: int = 48) -> list[int]:
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
    if not OCR_AVAILABLE:
        return pdf_path, False, "OCR 도구가 설치되어 있지 않습니다."

    enhanced_path = os.path.join(UPLOAD_DIR, f"{job_uid}_ocr.pdf")
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


@app.route("/")
def index():
    return render_template("index.html")


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

    auto_slide_count = _is_truthy(request.form.get("auto_slide_count"))
    enhance_scans = _is_truthy(request.form.get("enhance_scans"))
    try:
        slide_count = int(request.form.get("slide_count", 10))
    except (TypeError, ValueError):
        slide_count = 10
    slide_count = None if auto_slide_count else max(5, min(50, slide_count))

    page_range = request.form.get("page_range", "").strip()
    extra_prompt = request.form.get("extra_prompt", "").strip()

    uid = uuid.uuid4().hex[:8]
    pdf_path = os.path.join(UPLOAD_DIR, f"{uid}.pdf")
    file.save(pdf_path)
    analysis_pdf_path = pdf_path
    ocr_used = False
    ocr_error = None
    analyze_stage = "start"

    try:
        if enhance_scans:
            analyze_stage = "enhance_scans"
            analysis_pdf_path, ocr_used, ocr_error = _enhance_pdf_for_scans(pdf_path, uid)

        analyze_stage = "resolve_page_selection"
        page_plan = resolve_page_selection(analysis_pdf_path, page_range or None, max_pages_per_chunk=100)
        try:
            analyze_stage = "analyze_pdf_primary"
            slides_data = analyze_pdf(
                analysis_pdf_path,
                slide_count,
                page_range=page_range or None,
                extra_prompt=extra_prompt or None,
            )
        except UnicodeEncodeError:
            analyze_stage = "analyze_pdf_ascii_safe_retry"
            slides_data = analyze_pdf(
                analysis_pdf_path,
                slide_count,
                page_range=page_range or None,
                extra_prompt=extra_prompt or None,
                ascii_safe_mode=True,
            )
        analyze_stage = "review_slides"
        reviewed = review_slides(slides_data, selected_pages=page_plan["selected_pages"])
        analyze_stage = "collect_asset_pages"
        asset_pages = _candidate_asset_pages(reviewed["slides"], page_plan["selected_pages"])
        analyze_stage = "extract_pdf_images"
        assets = []
        if asset_pages:
            assets = extract_pdf_images(
                analysis_pdf_path,
                asset_pages,
                _asset_bundle_dir(uid),
                bundle_uid=uid,
            )
        analyze_stage = "attach_pdf_images"
        prepared_slides = attach_pdf_images_to_slides(reviewed["slides"], assets)
        prepared = {
            "slides": prepared_slides,
            "outline": build_outline(prepared_slides),
            "quality": build_quality_summary(prepared_slides),
        }
        analyze_stage = "build_response"
        return _json_response(
            {
                "ok": True,
                "slides": prepared["slides"],
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "assets": assets,
                "asset_count": len(assets),
                "uid": uid,
                "auto_slide_count": auto_slide_count,
                "page_plan": {
                    "mode": page_plan["mode"],
                    "selected_pages": page_plan["selected_pages"],
                    "selection_note": page_plan.get("selection_note", ""),
                },
                "ocr_available": OCR_AVAILABLE,
                "ocr_used": ocr_used,
                "ocr_error": ocr_error,
                "enhance_scans_requested": enhance_scans,
            }
        )
    except Exception as exc:
        _cleanup_asset_bundle(uid)
        error_id = _record_exception(f"api_analyze:{analyze_stage}", exc)
        return _json_response(
            {"error": _safe_error_text(exc), "error_id": error_id, "error_stage": analyze_stage},
            status=500,
        )
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if analysis_pdf_path != pdf_path and os.path.exists(analysis_pdf_path):
            os.remove(analysis_pdf_path)


@app.route("/api/presets")
def api_presets():
    result = []
    for preset_id, preset in PRESETS.items():
        colors = preset["colors"]
        result.append(
            {
                "id": preset_id,
                "name": preset["name"],
                "desc": preset["desc"],
                "swatch": {
                    "header": "#{:02X}{:02X}{:02X}".format(*colors["header"]),
                    "accent": "#{:02X}{:02X}{:02X}".format(*colors["accent"]),
                    "bg": "#{:02X}{:02X}{:02X}".format(*colors["bg"]),
                },
                "header_style": preset["header_style"],
                "bullet_style": preset["bullet_style"],
                "density": preset["density"],
            }
        )
    return jsonify(result)


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
    pdf_name = body.get("pdf_name", "강의교안")
    base_name = os.path.splitext(pdf_name)[0]

    if not slides_data:
        return jsonify({"error": "슬라이드 데이터 없음"}), 400

    uid = uuid.uuid4().hex[:8]
    download_name = _default_download_name(pdf_name)

    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        prepared_slides = prepared["slides"]

        _save_saved_payload(
            uid,
            {
                "slides": prepared_slides,
                "outline": prepared["outline"],
                "quality": prepared["quality"],
                "design": design,
                "assets": assets,
                "page_plan": page_plan,
                "pdf_name": pdf_name,
                "download_name": download_name,
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
    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        return jsonify(
            {
                "ok": True,
                "slides": prepared["slides"],
                "outline": prepared["outline"],
                "quality": prepared["quality"],
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
    pdf_name = body.get("pdf_name", payload.get("pdf_name", "강의교안"))

    download_name = _sanitize_download_name(
        body.get("download_name"),
        payload.get("download_name") or _default_download_name(pdf_name),
    )

    try:
        prepared = _prepare_slide_package(slides_data, assets, selected_pages=page_plan.get("selected_pages"))
        prepared_slides = prepared["slides"]
        updated_payload = {
            **payload,
            "slides": prepared_slides,
            "outline": prepared["outline"],
            "quality": prepared["quality"],
            "design": design,
            "assets": assets,
            "page_plan": page_plan,
            "pdf_name": pdf_name,
            "download_name": download_name,
        }
        _save_saved_payload(uid, updated_payload)
        return jsonify(
            {
                "ok": True,
                "preview_uid": uid,
                "slide_count": len(prepared_slides),
                "download_name": download_name,
            }
        )
    except Exception as exc:
        error_id = _record_exception("api_update_slides", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500


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

    design = payload.get("design") or {"preset": "corporate"}
    slides_data = payload.get("slides", [])
    assets = payload.get("assets", [])
    resolved_assets = _resolve_media_assets(assets)

    try:
        buf = generate_pptx_bytes(slides_data, design, resolved_assets)
    except Exception as exc:
        error_id = _record_exception("download_generate_pptx", exc)
        return jsonify({"error": _safe_error_text(exc), "error_id": error_id}), 500

    download_name = _sanitize_download_name(
        request.args.get("name"),
        payload.get("download_name") or "강의교안.pptx",
    )
    return send_file(
        buf,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5050))
    print(f"\n✅  http://localhost:{port}  에서 실행 중\n")
    app.run(host="0.0.0.0", port=port, debug=False)
