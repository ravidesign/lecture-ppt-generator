from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json

from flows.exam_pipeline import run_question_stage, run_review_stage
from flows.lecture_pipeline import (
    run_content_stage,
    run_curriculum_stage,
    run_fact_check_stage,
    run_layout_stage,
)
from tools.pdf_tool import build_page_source_excerpt, extract_selected_page_texts
from tools.slide_tool import build_exam_summary


AGENT_SPECS = [
    ("pm", "PM"),
    ("curriculum", "Curriculum"),
    ("content", "Content"),
    ("question", "Question"),
    ("fact_checker", "Fact Checker"),
    ("reviewer", "Reviewer"),
    ("layout", "Layout"),
    ("formatter", "Formatter"),
]


def _iso_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_initial_agent_trace() -> list[dict]:
    now = _iso_now()
    return [
        {
            "key": key,
            "label": label,
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "message": "대기 중",
            "attempt": 0,
            "updated_at": now,
        }
        for key, label in AGENT_SPECS
    ]


class AgentTrace:
    def __init__(self):
        self._rows = {row["key"]: row for row in build_initial_agent_trace()}

    def snapshot(self) -> list[dict]:
        return [deepcopy(self._rows[key]) for key, _ in AGENT_SPECS]

    def start(self, key: str, message: str):
        row = self._rows[key]
        row["status"] = "running"
        row["message"] = message
        row["attempt"] = int(row.get("attempt") or 0) + 1
        row["started_at"] = _iso_now()
        row["finished_at"] = None
        row["updated_at"] = row["started_at"]

    def complete(self, key: str, message: str):
        row = self._rows[key]
        row["status"] = "completed"
        row["message"] = message
        row["finished_at"] = _iso_now()
        row["updated_at"] = row["finished_at"]

    def revise(self, key: str, message: str):
        row = self._rows[key]
        row["status"] = "revise"
        row["message"] = message
        row["finished_at"] = _iso_now()
        row["updated_at"] = row["finished_at"]

    def fail(self, key: str, message: str):
        row = self._rows[key]
        row["status"] = "failed"
        row["message"] = message
        row["finished_at"] = _iso_now()
        row["updated_at"] = row["finished_at"]

    def set_formatter_pending(self):
        row = self._rows["formatter"]
        row["status"] = "queued"
        row["message"] = "최종 generate 단계에서 실행 예정"
        row["updated_at"] = _iso_now()


def _difficulty_total(settings: dict) -> int:
    return sum(
        max(0, int(settings.get(key, 0) or 0))
        for key in ("difficulty_easy", "difficulty_medium", "difficulty_hard")
    )


def _normalize_exam_settings(exam_settings: dict | None, pdf_name: str) -> dict:
    settings = dict(exam_settings or {})
    question_count = max(1, int(settings.get("question_count", 10) or 10))
    easy = max(0, int(settings.get("difficulty_easy", 20) or 20))
    medium = max(0, int(settings.get("difficulty_medium", 60) or 60))
    hard = max(0, int(settings.get("difficulty_hard", 20) or 20))
    total = max(1, easy + medium + hard)
    counts = {
        "difficulty_easy": round(question_count * easy / total),
        "difficulty_medium": round(question_count * medium / total),
    }
    counts["difficulty_hard"] = max(0, question_count - counts["difficulty_easy"] - counts["difficulty_medium"])
    return {
        "exam_enabled": settings.get("exam_enabled", True) is not False,
        "question_count": question_count,
        "difficulty_easy": counts["difficulty_easy"],
        "difficulty_medium": counts["difficulty_medium"],
        "difficulty_hard": counts["difficulty_hard"],
        "shuffle_versions": bool(settings.get("shuffle_versions")),
        "institution_name": str(settings.get("institution_name") or "").strip(),
        "exam_date": str(settings.get("exam_date") or "").strip(),
        "time_limit_minutes": int(settings.get("time_limit_minutes", 0) or 0),
        "course_name": str(settings.get("course_name") or pdf_name or "Teach-On 문제지").strip(),
    }


def _pm_summary_fallback(curriculum: dict, slides: list[dict], questions: list[dict]) -> dict:
    return {
        "status": "PASS",
        "summary": (
            f"학습목표 {len(curriculum.get('learning_objectives', []))}개, "
            f"슬라이드 {len(slides)}장, 문제 {len(questions)}문항을 기준으로 초안을 완료했습니다."
        ),
    }


def run_full_pipeline(
    *,
    uid: str,
    pdf_path: str,
    slide_count: int | None,
    page_range: str | None,
    extra_prompt: str | None,
    lecture_goal: str,
    page_plan: dict,
    page_plan_preview: dict,
    exam_settings: dict | None,
    asset_bundle_dir: str,
    pdf_name: str = "Teach-On",
    progress_cb=None,
):
    trace = AgentTrace()
    trace.set_formatter_pending()

    def notify(stage: str, message: str):
        if callable(progress_cb):
            progress_cb(stage, message, trace.snapshot())

    selected_pages = page_plan.get("selected_pages", [])
    page_texts = extract_selected_page_texts(pdf_path, selected_pages)
    source_excerpt = build_page_source_excerpt(page_texts)
    normalized_exam = _normalize_exam_settings(exam_settings, pdf_name)

    trace.start("pm", "작업 범위와 병렬 실행 계획을 조율하고 있습니다.")
    notify("pm_kickoff", "PM이 강의안과 시험지 생성을 조율하고 있습니다...")

    trace.start("curriculum", "선택 페이지를 바탕으로 커리큘럼을 설계하고 있습니다.")
    notify("curriculum", "선택 범위를 바탕으로 강의 구조를 정리하고 있습니다...")
    curriculum, _, curriculum_note = run_curriculum_stage(
        pdf_path=pdf_path,
        page_plan=page_plan,
        page_plan_preview=page_plan_preview,
        slide_count=slide_count,
        lecture_goal=lecture_goal,
    )
    trace.complete("curriculum", curriculum_note)
    notify("curriculum_completed", "커리큘럼 설계가 완료되었습니다.")

    slides = []
    questions_bundle = {"questions": []}
    with ThreadPoolExecutor(max_workers=2) as executor:
        trace.start("content", "슬라이드 초안을 작성하고 있습니다.")
        trace.start("question", "시험 문제 초안을 준비하고 있습니다.")
        notify("parallel_content_question", "슬라이드와 시험 문제 초안을 병렬로 생성하고 있습니다...")
        content_future = executor.submit(
            run_content_stage,
            pdf_path,
            slide_count,
            page_range,
            extra_prompt,
            lecture_goal,
            page_plan,
            curriculum,
            None,
        )
        question_future = executor.submit(
            run_question_stage,
            curriculum,
            [],
            normalized_exam["question_count"],
            normalized_exam,
            source_excerpt,
        )
        slides = content_future.result()
        questions_bundle, _, question_note = question_future.result()
    trace.complete("content", "슬라이드 초안 생성이 완료되었습니다.")
    trace.complete("question", question_note)
    notify("parallel_content_question_completed", "슬라이드와 시험 문제 초안 생성이 완료되었습니다.")

    fact_attempts = 0
    fact_result = {"status": "PASS", "issues": [], "revision_request": ""}
    while True:
        fact_attempts += 1
        trace.start("fact_checker", f"사실 검증 {fact_attempts}차를 진행하고 있습니다.")
        notify("fact_check", "슬라이드 초안을 검증하고 있습니다...")
        fact_result, _, fact_note = run_fact_check_stage(curriculum, slides, source_excerpt)
        if fact_result.get("status") == "PASS":
            trace.complete("fact_checker", fact_note)
            break
        if fact_result.get("status") == "REJECT" or fact_attempts >= 3:
            message = fact_result.get("revision_request") or "Fact checker rejected the draft"
            trace.fail("fact_checker", message)
            raise RuntimeError(message)
        trace.revise("fact_checker", fact_result.get("revision_request") or "수정 요청이 발생했습니다.")
        notify("fact_revise", "사실 검증 수정 요청이 발생해 슬라이드를 다시 작성하고 있습니다...")
        trace.start("content", f"Fact checker 수정 반영 {fact_attempts}차")
        slides = run_content_stage(
            pdf_path=pdf_path,
            slide_count=slide_count,
            page_range=page_range,
            extra_prompt=extra_prompt,
            lecture_goal=lecture_goal,
            page_plan=page_plan,
            curriculum=curriculum,
            revision_request=fact_result.get("revision_request"),
        )
        trace.complete("content", "Fact checker 수정 요청을 반영했습니다.")

    reviewed_questions = list(questions_bundle.get("questions") or [])
    if normalized_exam.get("exam_enabled"):
        review_attempts = 0
        while True:
            review_attempts += 1
            with ThreadPoolExecutor(max_workers=2) as executor:
                trace.start("reviewer", f"문항 검토 {review_attempts}차를 진행하고 있습니다.")
                notify("review_questions", "시험 문제와 정답 구성을 검토하고 있습니다...")
                review_future = executor.submit(run_review_stage, reviewed_questions, slides)
                review_result, _, review_note = review_future.result()
            if review_result.get("status") == "PASS":
                reviewed_questions = review_result.get("reviewed_questions") or reviewed_questions
                trace.complete("reviewer", review_note)
                break
            if review_attempts >= 3:
                message = "Reviewer가 문제 세트를 확정하지 못했습니다."
                trace.fail("reviewer", message)
                raise RuntimeError(message)
            trace.revise("reviewer", "Reviewer 수정 요청에 따라 문항을 다시 생성합니다.")
            notify("reviewer_revise", "Reviewer 피드백에 따라 문항을 다시 생성하고 있습니다...")
            trace.start("question", f"Reviewer 수정 반영 {review_attempts}차")
            questions_bundle, _, question_note = run_question_stage(
                curriculum,
                slides,
                normalized_exam["question_count"],
                normalized_exam,
                source_excerpt,
            )
            reviewed_questions = questions_bundle.get("questions") or []
            trace.complete("question", question_note)
    else:
        reviewed_questions = []
        trace.complete("reviewer", "시험지 생성이 비활성화되어 검토를 건너뛰었습니다.")

    trace.start("layout", "레이아웃과 이미지 전략을 적용하고 있습니다.")
    notify("layout", "슬라이드별 레이아웃과 이미지 배치를 정리하고 있습니다...")
    layout_result = run_layout_stage(
        uid=uid,
        pdf_path=pdf_path,
        slides=slides,
        page_plan=page_plan,
        asset_dir=asset_bundle_dir,
    )
    trace.complete("layout", "레이아웃과 이미지 연결을 적용했습니다.")
    notify("layout_completed", "슬라이드 레이아웃 적용이 완료되었습니다.")

    pm_summary = _pm_summary_fallback(curriculum, layout_result["slides"], reviewed_questions)
    try:
        from crews.full_crew import run_pm_review_stage

        trace.start("pm", "최종 결과를 점검하고 있습니다.")
        pm_result = run_pm_review_stage(
            json.dumps(curriculum, ensure_ascii=False),
            json.dumps(layout_result["slides"], ensure_ascii=False),
            json.dumps(reviewed_questions, ensure_ascii=False),
        )
        if isinstance(pm_result, dict):
            pm_summary = pm_result
    except Exception:
        pass
    trace.complete("pm", pm_summary.get("summary") or "전체 초안 검토를 완료했습니다.")
    notify("completed", "멀티 에이전트 초안 생성이 완료되었습니다.")

    return {
        "ok": True,
        "uid": uid,
        "slides": layout_result["slides"],
        "outline": layout_result["outline"],
        "quality": layout_result["quality"],
        "assets": layout_result["assets"],
        "asset_count": len(layout_result["assets"]),
        "lecture_goal": lecture_goal,
        "page_plan": {
            "mode": page_plan.get("mode"),
            "page_hint": page_plan.get("page_hint", ""),
            "selected_pages": selected_pages,
            "selection_note": page_plan.get("selection_note", ""),
        },
        "page_plan_preview": page_plan_preview,
        "curriculum": curriculum,
        "questions": reviewed_questions,
        "exam_summary": build_exam_summary(reviewed_questions),
        "exam_settings": normalized_exam,
        "agent_trace": trace.snapshot(),
        "pm_summary": pm_summary,
        "ocr_available": True,
    }
