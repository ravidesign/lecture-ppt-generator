import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")


def _load() -> list:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(data: list):
    temp_path = f"{HISTORY_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, HISTORY_FILE)


def add_record(pdf_name: str, uid: str, slide_count: int, theme: str):
    history = _load()
    history.insert(0, {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pdf_name": pdf_name,
        "uid": uid,
        "slide_count": slide_count,
        "theme": theme,
    })
    # 최대 50개 유지
    _save(history[:50])


def get_history() -> list:
    return _load()
