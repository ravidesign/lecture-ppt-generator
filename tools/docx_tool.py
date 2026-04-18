from __future__ import annotations

import os

import config


def generate_exam_artifacts(questions: list[dict], exam_settings: dict) -> dict:
    from core.docx_generator import build_exam_artifacts

    return build_exam_artifacts(questions, exam_settings)


def save_exam_artifacts(uid: str, questions: list[dict], exam_settings: dict) -> dict[str, dict]:
    artifacts = generate_exam_artifacts(questions, {**exam_settings, "uid": uid})
    saved = {}
    name_map = {
        "exam": f"{uid}_exam.docx",
        "answer": f"{uid}_answer.docx",
        "exam_a": f"{uid}_exam_a.docx",
        "exam_b": f"{uid}_exam_b.docx",
    }
    for kind, buf in artifacts.items():
        path = config.DOCX_DIR / name_map[kind]
        with open(path, "wb") as handle:
            handle.write(buf.getvalue())
        saved[kind] = {
            "kind": kind,
            "filename": name_map[kind],
            "path": str(path),
        }
    return saved
