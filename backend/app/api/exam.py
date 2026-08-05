"""
Exam API — formal examination mode (Fixed Paper + CAT-Exam).

Endpoints:
  POST /api/exam/generate          → Generate fixed exam paper, return questions (no correct_answer)
  POST /api/exam/start-cat         → Start CAT exam (adaptive but no feedback)
  POST /api/exam/{session_id}/submit  → Bulk submit fixed exam answers, receive IRT grade
  POST /api/exam/{session_id}/answer  → Answer one CAT-exam question (no feedback)
  GET  /api/exam/{session_id}/results → Retrieve completed exam grade

Security note: ExamQuestionOut deliberately omits correct_answer so it is never sent
to the client before submission. The answer is revealed per-question only in ExamGradeOut.
"""
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User, QuizSession, QuizResponse, UserTopicProgress
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic
from app.models.cat_knowledge import UserAbility
from app.schemas.question import (
    ExamConfig,
    ExamQuestionOut,
    ExamSubmitPayload,
    ExamGradeOut,
    ExamStartOut,
    ExamTopicScore,
    ExamQuestionDetail,
    CATAnswerSubmit,
    CATStepOut,
    LearningRecommendation,
    QuestionOut,
)
from app.engine.irt import estimate_ability_3pl, classify_mastery, theta_to_grade_10
from app.engine.question_selector import (
    generate_exam_paper,
    select_best_by_fisher,
    select_next_adaptive,
    prioritize_high_discrimination,
)
from app.engine.rules import classify_difficulty_level
from app.services.runtime_settings import get_effective_llm_runtime_config
from app.config import get_settings

router = APIRouter(prefix="/api/exam", tags=["exam"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROFILE_LABEL: dict[str, str] = {
    "easy": "Dễ",
    "balanced": "Cân bằng",
    "hard": "Khó",
    "personalized": "Cá nhân hóa",
}


def _safe_numeric(
    value: float | int | None,
    *,
    default: float,
    min_value: float,
    max_value: float,
    ndigits: int = 3,
) -> float:
    try:
        parsed = float(value) if value is not None else float(default)
    except (TypeError, ValueError):
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    return round(min(max(parsed, min_value), max_value), ndigits)


def _normalize_question_type(qtype: str | None) -> str:
    text = (qtype or "").strip().lower()
    if "nhận" in text or "nhan" in text:
        return "nhan_biet"
    if "thông" in text or "thong" in text:
        return "thong_hieu"
    if "vận" in text or "van" in text:
        return "van_dung"
    return text


def _is_sql_context(topic_name: str | None, major_topic_name: str | None) -> bool:
    text = f"{topic_name or ''} {major_topic_name or ''}".lower()
    sql_keywords = ["sql", "database", "cơ sở dữ liệu", "co so du lieu", "join", "query"]
    return any(k in text for k in sql_keywords)


def _question_to_exam_out(q: Question) -> ExamQuestionOut:
    """Convert ORM Question to ExamQuestionOut — no correct_answer."""
    return ExamQuestionOut(
        id=q.id,
        external_id=q.external_id,
        stem=q.stem,
        option_a=q.option_a,
        option_b=q.option_b,
        option_c=q.option_c,
        option_d=q.option_d,
        question_type=q.question_type,
        time_limit_seconds=q.time_limit_seconds,
        time_display=q.time_display,
        topic_name=q.topic.name if q.topic else "",
        major_topic_name=q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
    )


def _question_to_cat_out(q: Question) -> QuestionOut:
    """Convert ORM Question to CAT QuestionOut (reuses quiz schema, no correct_answer)."""
    return QuestionOut(
        id=q.id,
        external_id=q.external_id,
        stem=q.stem,
        option_a=q.option_a,
        option_b=q.option_b,
        option_c=q.option_c,
        option_d=q.option_d,
        question_type=q.question_type,
        time_limit_seconds=q.time_limit_seconds,
        time_display=q.time_display,
        topic_name=q.topic.name if q.topic else "",
        major_topic_name=q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
    )


def _classify_bloom(theta: float, scoring_data: list[dict]) -> Optional[str]:
    app_rows = [r for r in scoring_data if _normalize_question_type(r.get("question_type")) == "van_dung"]
    if not app_rows:
        return None
    app_acc = sum(1 for r in app_rows if r.get("is_correct")) / len(app_rows)
    if float(theta) > 1.5 and app_acc > 0.8:
        return "Xuất sắc - Có khả năng giải quyết vấn đề phức tạp"
    return None


def _build_topic_scores(scoring_data: list[dict]) -> dict[str, ExamTopicScore]:
    """Compute per-topic accuracy and mastery from scoring_data."""
    per_topic: dict[str, dict] = {}
    for row in scoring_data:
        name = row.get("topic_name") or str(row.get("topic_id", ""))
        if name not in per_topic:
            per_topic[name] = {"correct": 0, "total": 0, "responses": []}
        per_topic[name]["total"] += 1
        if row.get("is_correct"):
            per_topic[name]["correct"] += 1
        per_topic[name]["responses"].append(row)

    result: dict[str, ExamTopicScore] = {}
    for name, data in per_topic.items():
        topic_responses = [
            {"a": r["a"], "b": r["b"], "c": r["c"], "is_correct": r["is_correct"]}
            for r in data["responses"]
        ]
        ability = estimate_ability_3pl(topic_responses)
        topic_theta = ability["theta_map"]
        total = data["total"]
        correct = data["correct"]
        accuracy = correct / total if total > 0 else 0.0
        result[name] = ExamTopicScore(
            correct=correct,
            total=total,
            accuracy=round(accuracy, 4),
            mastery=classify_mastery(topic_theta),
            theta=round(topic_theta, 3),
        )
    return result


def _build_grade_out(
    session: QuizSession,
    responses: list[QuizResponse],
    scoring_data: list[dict],
) -> ExamGradeOut:
    """Build ExamGradeOut from completed session + responses."""
    ability = estimate_ability_3pl(scoring_data) if scoring_data else {
        "theta_map": 0.0,
        "posterior_sd": 1.0,
    }
    theta = _safe_numeric(ability["theta_map"], default=0.0, min_value=-6.0, max_value=6.0)
    posterior_sd = _safe_numeric(ability["posterior_sd"], default=1.0, min_value=0.0, max_value=10.0)

    grade_info = theta_to_grade_10(theta)
    irt_score_10 = grade_info["irt_score_10"]
    grade_label = grade_info["grade_label"]

    correct_count = sum(1 for r in responses if r.is_correct)
    total_count = len(responses)
    accuracy = correct_count / total_count if total_count > 0 else 0.0
    raw_score_10 = round((correct_count / total_count) * 10, 1) if total_count > 0 else 0.0

    topic_scores = _build_topic_scores(scoring_data)
    bloom_classification = _classify_bloom(theta, scoring_data)

    per_question_detail: list[ExamQuestionDetail] = []
    for r in responses:
        q = r.question
        per_question_detail.append(ExamQuestionDetail(
            question_id=q.id,
            external_id=q.external_id,
            stem=q.stem,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer,   # revealed after submission
            user_answer=r.user_answer,
            is_correct=bool(r.is_correct),
            difficulty_b=float(q.difficulty_b),
            discrimination_a=float(q.discrimination_a),
            guessing_c=float(q.guessing_c),
            question_type=q.question_type or "",
            time_spent_seconds=r.time_spent_seconds or 0,
            topic_name=q.topic.name if q.topic else "",
        ))

    return ExamGradeOut(
        session_id=session.id,
        exam_type=session.exam_type or "fixed",
        difficulty_profile=session.difficulty_profile or "balanced",
        correct_count=correct_count,
        total_count=total_count,
        accuracy=round(accuracy, 4),
        raw_score_10=raw_score_10,
        theta=theta,
        posterior_sd=posterior_sd,
        irt_score_10=irt_score_10,
        grade_label=grade_label,
        bloom_classification=bloom_classification,
        topic_scores=topic_scores,
        per_question_detail=per_question_detail,
        time_limit_seconds=session.global_time_limit_seconds or 0,
        started_at=session.started_at.isoformat() if session.started_at else None,
        completed_at=session.completed_at.isoformat() if session.completed_at else None,
    )


async def _update_user_ability_and_progress(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    theta: float,
    posterior_sd: float,
    answered_count: int,
    scoring_data: list[dict],
) -> None:
    """Persist ability estimate and per-topic progress after exam completion."""
    ua_result = await db.execute(
        select(UserAbility).where(
            UserAbility.user_id == user_id,
            UserAbility.subject_id == subject_id,
        )
    )
    user_ability = ua_result.scalar_one_or_none()
    if not user_ability:
        user_ability = UserAbility(user_id=user_id, subject_id=subject_id)
        db.add(user_ability)
    user_ability.theta_estimate = theta
    user_ability.sem = posterior_sd
    user_ability.answered_count = answered_count

    # Per-topic progress
    per_topic: dict[int, dict] = {}
    for row in scoring_data:
        tid = row.get("topic_id")
        if tid is None:
            continue
        if tid not in per_topic:
            per_topic[tid] = {"responses": [], "topic_name": row.get("topic_name", "")}
        per_topic[tid]["responses"].append(row)

    for topic_id, data in per_topic.items():
        topic_responses = [
            {"a": r["a"], "b": r["b"], "c": r["c"], "is_correct": r["is_correct"]}
            for r in data["responses"]
        ]
        topic_ability = estimate_ability_3pl(topic_responses)
        topic_theta = topic_ability["theta_map"]
        mastery = classify_mastery(topic_theta)
        correct = sum(1 for r in data["responses"] if r.get("is_correct"))
        total = len(data["responses"])

        prog_result = await db.execute(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user_id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        prog = prog_result.scalar_one_or_none()
        if not prog:
            prog = UserTopicProgress(user_id=user_id, topic_id=topic_id)
            db.add(prog)
        prog.theta_estimate = topic_theta
        prog.mastery_level = mastery
        prog.questions_attempted = (prog.questions_attempted or 0) + total
        prog.questions_correct = (prog.questions_correct or 0) + correct


# ---------------------------------------------------------------------------
# POST /api/exam/generate — Fixed-mode exam paper generation
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=ExamStartOut)
async def generate_exam(
    config: ExamConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Generate a fixed exam paper based on the requested configuration.

    Returns the full question list (WITHOUT correct_answer) and the session_id.
    The client must call POST /api/exam/{session_id}/submit to receive the grade.
    """
    if config.exam_type != "fixed":
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/exam/start-cat for cat_exam type",
        )

    valid_profiles = {"easy", "balanced", "hard", "personalized"}
    if config.difficulty_profile not in valid_profiles:
        raise HTTPException(
            status_code=400,
            detail=f"difficulty_profile must be one of {sorted(valid_profiles)}",
        )

    # ------------------------------------------------------------------
    # 1. Load question pool
    # ------------------------------------------------------------------
    query = (
        select(Question)
        .join(Topic, Topic.id == Question.topic_id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == config.subject_id)
        .where(Question.is_archived.is_(False))
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    if config.topic_ids:
        query = query.where(Question.topic_id.in_(config.topic_ids))

    result = await db.execute(query)
    all_questions = result.scalars().unique().all()

    if not all_questions:
        raise HTTPException(status_code=404, detail="No questions found for this subject/topic filter")

    # ------------------------------------------------------------------
    # 2. Get prior_theta for personalized profile
    # ------------------------------------------------------------------
    prior_theta = 0.0
    if config.difficulty_profile == "personalized":
        ua_result = await db.execute(
            select(UserAbility).where(
                UserAbility.user_id == user.id,
                UserAbility.subject_id == config.subject_id,
            )
        )
        ua = ua_result.scalar_one_or_none()
        if ua and ua.theta_estimate is not None:
            prior_theta = float(ua.theta_estimate)

    # ------------------------------------------------------------------
    # 3. Generate exam paper using IRT-based selection
    # ------------------------------------------------------------------
    question_dicts = [
        {
            "id": q.id,
            "topic_id": q.topic_id,
            "question_type": q.question_type,
            "discrimination_a": float(q.discrimination_a),
            "difficulty_b": float(q.difficulty_b),
            "guessing_c": float(q.guessing_c),
            "time_limit_seconds": q.time_limit_seconds,
        }
        for q in all_questions
    ]

    paper = generate_exam_paper(
        questions=question_dicts,
        num_questions=config.num_questions,
        difficulty_profile=config.difficulty_profile,
        recognition_pct=config.recognition_pct,
        comprehension_pct=config.comprehension_pct,
        application_pct=config.application_pct,
        prior_theta=prior_theta,
        topic_ids=config.topic_ids,
    )

    selected_ids = [q["id"] for q in paper["questions"]]
    if not selected_ids:
        raise HTTPException(
            status_code=404,
            detail="Could not select enough questions for the requested configuration",
        )

    # ------------------------------------------------------------------
    # 4. Compute time limit
    # ------------------------------------------------------------------
    exam_metadata = paper["exam_metadata"]
    time_limit = (
        int(config.time_limit_override)
        if config.time_limit_override
        else int(exam_metadata["total_time_seconds"])
    )
    # Minimum 5 minutes, maximum 3 hours
    time_limit = max(300, min(10800, time_limit))

    # ------------------------------------------------------------------
    # 5. Persist session + placeholder responses
    # ------------------------------------------------------------------
    session = QuizSession(
        user_id=user.id,
        subject_id=config.subject_id,
        total_questions=len(selected_ids),
        theta_estimate=0,
        exam_mode=True,
        exam_type="fixed",
        difficulty_profile=config.difficulty_profile,
        global_time_limit_seconds=time_limit,
    )
    db.add(session)
    await db.flush()

    # Pre-create QuizResponse rows with user_answer=None as placeholders.
    # This allows us to validate the set of questions later on submit.
    for question_id in selected_ids:
        placeholder = QuizResponse(
            session_id=session.id,
            question_id=question_id,
            is_correct=False,
            guessing_flag=False,
        )
        db.add(placeholder)

    await db.commit()
    await db.refresh(session)

    # ------------------------------------------------------------------
    # 6. Build response — questions ordered as generated (randomly shuffled)
    # ------------------------------------------------------------------
    q_map = {q.id: q for q in all_questions}
    exam_questions_out = [
        _question_to_exam_out(q_map[qid])
        for qid in selected_ids
        if qid in q_map
    ]

    return ExamStartOut(
        session_id=session.id,
        questions=exam_questions_out,
        time_limit_seconds=time_limit,
        exam_metadata=exam_metadata,
    )


# ---------------------------------------------------------------------------
# POST /api/exam/{session_id}/submit — Fixed-mode bulk answer submission
# ---------------------------------------------------------------------------

@router.post("/{session_id}/submit", response_model=ExamGradeOut)
async def submit_exam(
    session_id: int,
    payload: ExamSubmitPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Submit all answers for a fixed-mode exam in a single request.

    - Validates the session belongs to the user and is fixed-mode.
    - Records each answer, computes is_correct, detects guessing.
    - Runs Bayesian EAP to estimate theta.
    - Maps theta → 10-point IRT grade.
    - Returns ExamGradeOut with answers revealed per question.
    """
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam session not found")
    if not session.exam_mode or session.exam_type != "fixed":
        raise HTTPException(status_code=400, detail="This session is not a fixed exam")
    if session.completed_at:
        raise HTTPException(status_code=400, detail="Exam already submitted")

    # ------------------------------------------------------------------
    # 1. Load the placeholder responses to get authoritative question list
    # ------------------------------------------------------------------
    placeholders_result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .options(selectinload(QuizResponse.question).selectinload(Question.topic).selectinload(Topic.major_topic))
        .order_by(QuizResponse.id.asc())
    )
    placeholder_rows = placeholders_result.scalars().all()
    if not placeholder_rows:
        raise HTTPException(status_code=400, detail="No questions found for this exam session")

    # ------------------------------------------------------------------
    # 2. Record answers
    # ------------------------------------------------------------------
    now = datetime.now(timezone.utc)
    correct_count = 0
    scoring_data: list[dict] = []

    for row in placeholder_rows:
        q = row.question
        user_ans = payload.answers.get(q.id)
        time_spent = payload.time_spent.get(q.id, 0)

        if user_ans is not None:
            user_ans_upper = user_ans.upper()
            is_correct = user_ans_upper == q.correct_answer.upper()
            # Guessing detection: correct + very fast + high c
            guessing = is_correct and time_spent < 10 and float(q.guessing_c) > 0.2
        else:
            # Unanswered — treat as wrong, no guessing
            user_ans_upper = None
            is_correct = False
            guessing = False

        row.user_answer = user_ans_upper
        row.is_correct = is_correct
        row.guessing_flag = guessing
        row.time_spent_seconds = time_spent
        row.answered_at = now

        if is_correct:
            correct_count += 1

        scoring_data.append({
            "a": float(q.discrimination_a),
            "b": float(q.difficulty_b),
            "c": float(q.guessing_c),
            "is_correct": is_correct,
            "topic_id": q.topic_id,
            "topic_name": q.topic.name if q.topic else str(q.topic_id),
            "major_topic_name": q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            "question_type": q.question_type or "",
            "guessing_flag": guessing,
            "difficulty_level": classify_difficulty_level(float(q.difficulty_b)),
        })

    # ------------------------------------------------------------------
    # 3. Estimate ability via Bayesian EAP
    # ------------------------------------------------------------------
    ability = estimate_ability_3pl(scoring_data)
    theta = _safe_numeric(ability["theta_map"], default=0.0, min_value=-6.0, max_value=6.0)
    posterior_sd = _safe_numeric(ability["posterior_sd"], default=1.0, min_value=0.0, max_value=10.0)

    # ------------------------------------------------------------------
    # 4. Finalise session
    # ------------------------------------------------------------------
    total_count = len(placeholder_rows)
    session.correct_answers = correct_count
    session.theta_estimate = theta
    session.total_score = round((correct_count / total_count) * 100, 2) if total_count > 0 else 0.0
    session.completed_at = now

    # ------------------------------------------------------------------
    # 5. Update per-user ability and topic progress
    # ------------------------------------------------------------------
    await _update_user_ability_and_progress(
        db=db,
        user_id=user.id,
        subject_id=session.subject_id,
        theta=theta,
        posterior_sd=posterior_sd,
        answered_count=total_count,
        scoring_data=scoring_data,
    )

    await db.commit()

    # Reload responses with proper ORM objects for _build_grade_out
    responses_result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .options(selectinload(QuizResponse.question).selectinload(Question.topic).selectinload(Topic.major_topic))
        .order_by(QuizResponse.id.asc())
    )
    responses = responses_result.scalars().all()

    return _build_grade_out(session, responses, scoring_data)


# ---------------------------------------------------------------------------
# POST /api/exam/start-cat — Start CAT-Exam (adaptive, no feedback)
# ---------------------------------------------------------------------------

@router.post("/start-cat", response_model=CATStepOut)
async def start_cat_exam(
    config: ExamConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Start an adaptive CAT exam session.

    Identical to practice CAT except:
    - session.exam_mode = True
    - CATStepOut returns theta=0, sem=999 (hidden from client at UI layer)
    - applied_rules is empty list (not shown during exam)
    """
    if config.exam_type != "cat_exam":
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/exam/generate for fixed exam type",
        )

    settings = get_settings()

    query = (
        select(Question)
        .join(Topic, Topic.id == Question.topic_id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == config.subject_id)
        .where(Question.is_archived.is_(False))
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    if config.topic_ids:
        query = query.where(Question.topic_id.in_(config.topic_ids))

    result = await db.execute(query)
    pool = result.scalars().unique().all()

    # Get prior theta for difficulty targeting
    prior_theta = 0.0
    if config.difficulty_profile == "personalized":
        ua_result = await db.execute(
            select(UserAbility).where(
                UserAbility.user_id == user.id,
                UserAbility.subject_id == config.subject_id,
            )
        )
        ua = ua_result.scalar_one_or_none()
        if ua and ua.theta_estimate is not None:
            prior_theta = float(ua.theta_estimate)
    elif config.difficulty_profile == "easy":
        prior_theta = -1.0
    elif config.difficulty_profile == "hard":
        prior_theta = 1.0

    time_limit = int(config.time_limit_override or (config.num_questions * 90))
    time_limit = max(300, min(10800, time_limit))

    session = QuizSession(
        user_id=user.id,
        subject_id=config.subject_id,
        total_questions=config.num_questions,
        theta_estimate=prior_theta,
        exam_mode=True,
        exam_type="cat_exam",
        difficulty_profile=config.difficulty_profile,
        global_time_limit_seconds=time_limit,
    )
    db.add(session)
    await db.flush()

    if not pool:
        raise HTTPException(status_code=404, detail="No questions found for this subject")

    candidate_dicts = [
        {
            "id": q.id,
            "topic_id": q.topic_id,
            "question_type": q.question_type,
            "discrimination_a": float(q.discrimination_a),
            "difficulty_b": float(q.difficulty_b),
            "guessing_c": float(q.guessing_c),
        }
        for q in pool
    ]

    # Seed theta from difficulty profile for initial question selection
    seed_theta = prior_theta

    # R1-style initialization: use profile-based starting point
    r1_range = (seed_theta - 0.5, seed_theta + 0.5)
    r1_candidates = [
        q for q in candidate_dicts
        if r1_range[0] <= float(q["difficulty_b"]) <= r1_range[1]
        and float(q["discrimination_a"]) > 1.2
    ]
    next_q_dict = select_best_by_fisher(r1_candidates, current_theta=seed_theta)
    if not next_q_dict:
        opening = prioritize_high_discrimination(candidate_dicts, top_n=10)
        next_q_dict = select_best_by_fisher(opening, current_theta=seed_theta)
    if not next_q_dict:
        next_q_dict = select_next_adaptive(candidate_dicts, current_theta=seed_theta, answered_ids=set())

    next_question = None
    if next_q_dict:
        next_question = next((q for q in pool if q.id == next_q_dict["id"]), None)

    await db.commit()

    return CATStepOut(
        session_id=session.id,
        question=_question_to_cat_out(next_question) if next_question else None,
        theta=0.0,
        sem=999.0,
        answered_count=0,
        max_questions=config.num_questions,
        is_completed=False,
        bloom_classification=None,
        applied_rules=[],       # No rules revealed during exam
        theta_history=[0.0],
        recommendations=[],
    )


# ---------------------------------------------------------------------------
# POST /api/exam/{session_id}/answer — CAT-Exam answer (one question at a time)
# ---------------------------------------------------------------------------

@router.post("/{session_id}/answer", response_model=CATStepOut)
async def answer_cat_exam_question(
    session_id: int,
    payload: CATAnswerSubmit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Submit a single answer in a CAT-exam session.

    Identical behaviour to practice CAT (theta is updated, next question selected via
    Fisher information), EXCEPT the response does NOT reveal theta/sem/applied_rules
    to prevent ability disclosure during an active exam.

    On completion the client should redirect to GET /api/exam/{session_id}/results.
    """
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam session not found")
    if not session.exam_mode or session.exam_type != "cat_exam":
        raise HTTPException(status_code=400, detail="This session is not a CAT exam")
    if session.completed_at:
        raise HTTPException(status_code=400, detail="Exam already completed")

    q_result = await db.execute(
        select(Question)
        .where(Question.id == payload.question_id)
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    question = q_result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Prevent double-answer
    existing = await db.execute(
        select(QuizResponse).where(
            QuizResponse.session_id == session_id,
            QuizResponse.question_id == payload.question_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Question already answered in this session")

    is_correct = payload.user_answer.upper() == question.correct_answer.upper()
    guessing = is_correct and (payload.time_spent_seconds or 0) < 10 and float(question.guessing_c) > 0.2

    response_row = QuizResponse(
        session_id=session_id,
        question_id=payload.question_id,
        user_answer=payload.user_answer.upper(),
        is_correct=is_correct,
        guessing_flag=guessing,
        time_spent_seconds=payload.time_spent_seconds,
    )
    db.add(response_row)
    await db.flush()

    # Reload all responses
    responses_result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .order_by(QuizResponse.id.asc())
        .options(selectinload(QuizResponse.question).selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    responses = responses_result.scalars().all()

    scoring_data = []
    for r in responses:
        q = r.question
        scoring_data.append({
            "a": float(q.discrimination_a),
            "b": float(q.difficulty_b),
            "c": float(q.guessing_c),
            "is_correct": r.is_correct,
            "topic_id": q.topic_id,
            "topic_name": q.topic.name if q.topic else str(q.topic_id),
            "major_topic_name": q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            "question_type": q.question_type or "",
            "guessing_flag": bool(r.guessing_flag),
            "difficulty_level": classify_difficulty_level(float(q.difficulty_b)),
        })

    ability = estimate_ability_3pl(scoring_data)
    raw_theta = ability["theta_map"]

    # Apply R7-style dampening for guessing
    if guessing:
        prev_theta = float(session.theta_estimate or 0.0)
        theta = prev_theta + 0.3 * (raw_theta - prev_theta)
    else:
        theta = raw_theta
    theta = _safe_numeric(theta, default=0.0, min_value=-6.0, max_value=6.0)
    sem = _safe_numeric(ability["posterior_sd"], default=999.0, min_value=0.0, max_value=999.0)

    answered_count = len(responses)
    max_questions = int(session.total_questions or 20)

    is_completed = False
    stop_reason = None
    if sem < 0.3:
        is_completed = True
        stop_reason = "SEM < 0.3"
    elif answered_count >= max_questions:
        is_completed = True
        stop_reason = "Đạt số câu tối đa"

    session.theta_estimate = theta
    session.correct_answers = sum(1 for r in responses if r.is_correct)

    # Update UserAbility
    ua_result = await db.execute(
        select(UserAbility).where(
            UserAbility.user_id == user.id,
            UserAbility.subject_id == session.subject_id,
        )
    )
    user_ability = ua_result.scalar_one_or_none()
    if not user_ability:
        user_ability = UserAbility(user_id=user.id, subject_id=session.subject_id)
        db.add(user_ability)
    user_ability.theta_estimate = theta
    user_ability.sem = sem
    user_ability.answered_count = answered_count

    next_question_out = None

    if is_completed:
        session.completed_at = datetime.now(timezone.utc)
        session.total_score = round(
            (session.correct_answers / answered_count) * 100, 2
        ) if answered_count > 0 else 0.0
        await _update_user_ability_and_progress(
            db=db,
            user_id=user.id,
            subject_id=session.subject_id,
            theta=theta,
            posterior_sd=sem,
            answered_count=answered_count,
            scoring_data=scoring_data,
        )
    else:
        # Select next question via Fisher information (full CAT logic simplified for exam)
        answered_ids = {r.question_id for r in responses}
        candidate_rows = await db.execute(
            select(
                Question.id,
                Question.topic_id,
                Question.question_type,
                Question.discrimination_a,
                Question.difficulty_b,
                Question.guessing_c,
            )
            .join(Topic, Topic.id == Question.topic_id)
            .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
            .where(MajorTopic.subject_id == session.subject_id)
            .where(Question.is_archived.is_(False))
        )
        candidate_dicts = [
            {
                "id": row.id,
                "topic_id": row.topic_id,
                "question_type": row.question_type,
                "discrimination_a": float(row.discrimination_a),
                "difficulty_b": float(row.difficulty_b),
                "guessing_c": float(row.guessing_c),
            }
            for row in candidate_rows
        ]
        next_q_dict = select_next_adaptive(candidate_dicts, current_theta=theta, answered_ids=answered_ids)
        if next_q_dict:
            nq_result = await db.execute(
                select(Question)
                .where(Question.id == next_q_dict["id"])
                .options(selectinload(Question.topic).selectinload(Topic.major_topic))
            )
            nq = nq_result.scalar_one_or_none()
            if nq:
                next_question_out = _question_to_cat_out(nq)

        if not next_question_out:
            is_completed = True
            stop_reason = "Hết câu hỏi phù hợp"
            session.completed_at = datetime.now(timezone.utc)
            session.total_score = round(
                (session.correct_answers / answered_count) * 100, 2
            ) if answered_count > 0 else 0.0

    await db.commit()

    # Return CATStepOut — during exam, theta/sem/applied_rules are masked
    return CATStepOut(
        session_id=session.id,
        question=next_question_out,
        # Mask ability info during active exam; 0/999 signals "in progress"
        theta=0.0 if not is_completed else round(theta, 3),
        sem=999.0 if not is_completed else round(sem, 3),
        answered_count=answered_count,
        max_questions=max_questions,
        is_completed=is_completed,
        stop_reason=stop_reason,
        bloom_classification=None,
        applied_rules=[],       # No rule disclosure during exam
        theta_history=[],       # No history disclosure during exam
        recommendations=[],
    )


# ---------------------------------------------------------------------------
# GET /api/exam/{session_id}/results — Retrieve exam grading result
# ---------------------------------------------------------------------------

@router.get("/{session_id}/results", response_model=ExamGradeOut)
async def get_exam_results(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return the grading result for a completed exam session.

    Reveals correct_answer per question in ExamGradeOut.per_question_detail.
    Available only after session.completed_at is set.
    """
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam session not found")
    if not session.exam_mode:
        raise HTTPException(status_code=400, detail="This is not an exam session")
    if not session.completed_at:
        raise HTTPException(status_code=400, detail="Exam not yet completed")

    responses_result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .where(QuizResponse.user_answer.isnot(None))
        .options(selectinload(QuizResponse.question).selectinload(Question.topic).selectinload(Topic.major_topic))
        .order_by(QuizResponse.id.asc())
    )
    responses = responses_result.scalars().all()

    scoring_data = [
        {
            "a": float(r.question.discrimination_a),
            "b": float(r.question.difficulty_b),
            "c": float(r.question.guessing_c),
            "is_correct": bool(r.is_correct),
            "topic_id": r.question.topic_id,
            "topic_name": r.question.topic.name if r.question.topic else str(r.question.topic_id),
            "major_topic_name": r.question.topic.major_topic.name
                if r.question.topic and r.question.topic.major_topic else "",
            "question_type": r.question.question_type or "",
            "guessing_flag": bool(r.guessing_flag),
            "difficulty_level": classify_difficulty_level(float(r.question.difficulty_b)),
        }
        for r in responses
    ]

    return _build_grade_out(session, responses, scoring_data)
