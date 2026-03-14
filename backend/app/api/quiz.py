"""Quiz API: Create quiz, submit answers, get results."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User, QuizSession, QuizResponse, UserTopicProgress, InferenceRuleLog
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic, TopicPrerequisite, Subject
from app.models.cat_knowledge import UserAbility
from app.schemas.question import (
    QuizConfig, QuestionOut, QuizSessionOut, AnswerSubmit,
    QuizResultOut, QuizResultDetail, QuestionWithAnswer, CATAnswerSubmit, CATStepOut,
    LearningRecommendation, LLMGenerateRequest, GeneratedQuestionOut,
    CalibrationReport, CalibrationBin, InferenceRuleLogOut,
)
from app.engine.question_selector import (
    prioritize_high_discrimination,
    select_best_by_fisher,
    select_quiz_questions,
    select_next_adaptive,
)
from app.engine.scoring import score_quiz
from app.engine.irt import estimate_theta, standard_error_of_measurement
from app.engine.rules import topic_error_rates, classify_difficulty_level
from app.engine.llm_generation import generate_question_from_topic, generate_validated_question_for_cat
from app.config import get_settings
from app.services.runtime_settings import get_effective_llm_runtime_config

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _question_signature_from_payload(payload: dict) -> str:
    return "|".join(
        [
            _normalize_text(str(payload.get("stem", ""))),
            _normalize_text(str(payload.get("option_a", ""))),
            _normalize_text(str(payload.get("option_b", ""))),
            _normalize_text(str(payload.get("option_c", ""))),
            _normalize_text(str(payload.get("option_d", ""))),
            _normalize_text(str(payload.get("correct_answer", ""))),
        ]
    )


def _question_signature_from_model(q: Question) -> str:
    return "|".join(
        [
            _normalize_text(q.stem),
            _normalize_text(q.option_a),
            _normalize_text(q.option_b),
            _normalize_text(q.option_c),
            _normalize_text(q.option_d),
            _normalize_text(q.correct_answer),
        ]
    )


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


def _pick_min_b_gap(candidates: list[dict], target_b: float) -> dict | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda q: (abs(float(q["difficulty_b"]) - float(target_b)), -float(q.get("discrimination_a", 0.0))),
    )


def _compute_sql_ratio(scoring_data: list[dict]) -> float:
    if not scoring_data:
        return 0.0
    sql_count = sum(1 for r in scoring_data if r.get("is_sql"))
    return sql_count / len(scoring_data)


def _compute_sql_accuracy(scoring_data: list[dict]) -> float:
    sql_rows = [r for r in scoring_data if r.get("is_sql")]
    if not sql_rows:
        return 1.0
    correct = sum(1 for r in sql_rows if r.get("is_correct"))
    return correct / len(sql_rows)


def _classify_bloom(theta: float, scoring_data: list[dict]) -> str | None:
    app_rows = [r for r in scoring_data if _normalize_question_type(r.get("question_type")) == "van_dung"]
    app_acc = sum(1 for r in app_rows if r.get("is_correct")) / len(app_rows) if app_rows else 0.0
    if float(theta) > 1.5 and app_acc > 0.8:
        return "Xuất sắc - Có khả năng giải quyết vấn đề phức tạp"
    return None


def _append_rule(
    applied_rules: list[str],
    rule_events: list[dict],
    rule_code: str,
    reason: str,
    question_id: int | None = None,
):
    if rule_code not in applied_rules:
        applied_rules.append(rule_code)
        rule_events.append(
            {
                "rule_code": rule_code,
                "reason": reason,
                "question_id": question_id,
            }
        )


def _question_to_out(q: Question) -> QuestionOut:
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


def _theta_history_from_responses(responses: list[QuizResponse]) -> list[float]:
    history = [0.0]
    scoring_data = []
    current_theta = 0.0
    for r in responses:
        q = r.question
        scoring_data.append({
            "a": float(q.discrimination_a),
            "b": float(q.difficulty_b),
            "c": float(q.guessing_c),
            "is_correct": r.is_correct,
        })
        current_theta = estimate_theta(scoring_data, initial_theta=current_theta)
        history.append(round(current_theta, 3))
    return history


async def _recent_answered_question_ids(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    window_size: int,
) -> set[int]:
    """Return recently answered question ids for a user+subject across sessions."""
    if window_size <= 0:
        return set()

    rows = await db.execute(
        select(QuizResponse.question_id)
        .select_from(QuizResponse)
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .where(QuizSession.user_id == user_id)
        .where(QuizSession.subject_id == subject_id)
        .where(QuizResponse.user_answer.isnot(None))
        .order_by(QuizResponse.answered_at.desc(), QuizResponse.id.desc())
        .limit(window_size)
    )
    return {row.question_id for row in rows}


async def _build_recommendations(db: AsyncSession, responses: list[QuizResponse]) -> list[LearningRecommendation]:
    scored = [
        {
            "topic_id": r.question.topic_id,
            "is_correct": r.is_correct,
        }
        for r in responses
    ]
    error_by_topic = topic_error_rates(scored)
    weak_topic_ids = [tid for tid, rate in error_by_topic.items() if rate > 0.6]
    if not weak_topic_ids:
        return []

    tp_result = await db.execute(
        select(TopicPrerequisite).where(TopicPrerequisite.topic_id.in_(weak_topic_ids))
    )
    prereq_rows = tp_result.scalars().all()
    if not prereq_rows:
        return []

    topic_ids = set(weak_topic_ids)
    for row in prereq_rows:
        topic_ids.add(row.prerequisite_topic_id)

    topics_result = await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))
    topics = {t.id: t for t in topics_result.scalars().all()}

    recommendations: list[LearningRecommendation] = []
    for row in prereq_rows:
        current_topic = topics.get(row.topic_id)
        prereq_topic = topics.get(row.prerequisite_topic_id)
        if not current_topic:
            continue
        recommendations.append(
            LearningRecommendation(
                topic_id=current_topic.id,
                topic_name=current_topic.name,
                prerequisite_topic_id=prereq_topic.id if prereq_topic else None,
                prerequisite_topic_name=prereq_topic.name if prereq_topic else None,
                reason=f"Tỷ lệ sai > 60% ở topic '{current_topic.name}'",
            )
        )
    return recommendations


def _target_level_from_theta(theta: float) -> str:
    if theta < -0.5:
        return "Nhận biết"
    if theta < 0.7:
        return "Thông hiểu"
    return "Vận dụng"


async def _build_topic_context(db: AsyncSession, topic_id: int) -> str:
    topic = await db.get(Topic, topic_id)
    if not topic:
        return ""

    prereq_result = await db.execute(
        select(TopicPrerequisite).where(TopicPrerequisite.topic_id == topic_id)
    )
    prereq_links = prereq_result.scalars().all()
    prereq_ids = [p.prerequisite_topic_id for p in prereq_links]
    prereq_names: list[str] = []
    if prereq_ids:
        pre_topics_result = await db.execute(select(Topic).where(Topic.id.in_(prereq_ids)))
        prereq_names = [t.name for t in pre_topics_result.scalars().all()]

    base = f"Topic: {topic.name}."
    if prereq_names:
        base += " Tiên quyết: " + ", ".join(prereq_names) + "."
    return base


async def _pick_start_topic_id_for_cat(
    db: AsyncSession,
    subject_id: int,
    topic_ids: list[int] | None = None,
) -> int | None:
    query = (
        select(Topic.id)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc(), Topic.id.asc())
        .limit(1)
    )
    if topic_ids:
        query = query.where(Topic.id.in_(topic_ids))

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _generate_and_persist_cat_question(
    db: AsyncSession,
    user_id: int,
    subject_id: int,
    topic_id: int,
    theta: float,
    blocked_signatures: set[str] | None = None,
    llm_runtime_settings: dict | None = None,
) -> Question | None:
    """Generate CAT-targeted question via LLM, validate, then persist to question bank."""
    topic = await db.get(Topic, topic_id)
    if not topic:
        return None

    target_level = _target_level_from_theta(theta)
    target_b = max(-2.5, min(2.5, float(theta)))
    target_a = 1.5 if target_level == "Vận dụng" else (1.2 if target_level == "Thông hiểu" else 1.0)
    target_c = 0.2 if target_level != "Vận dụng" else 0.15

    context = await _build_topic_context(db, topic_id)
    blocked_signatures = blocked_signatures or set()

    generated = None
    for attempt in range(3):
        gen_context = context
        if attempt > 0:
            gen_context += " Tránh sinh lại câu đã xuất hiện trước đó trong phiên làm bài."

        candidate_generated = generate_validated_question_for_cat(
            topic_name=topic.name,
            knowledge_context=gen_context,
            target_level=target_level,
            target_b=target_b,
            target_a=target_a,
            target_c=target_c,
            runtime_settings=llm_runtime_settings,
        )
        candidate_signature = _question_signature_from_payload(candidate_generated)
        if candidate_signature in blocked_signatures:
            continue

        stem_norm = _normalize_text(candidate_generated["stem"])
        existing_same_stem = await db.execute(
            select(Question).where(
                Question.topic_id == topic_id,
                func.lower(func.trim(Question.stem)) == stem_norm,
            ).limit(1)
        )
        existing_question = existing_same_stem.scalars().first()
        if existing_question:
            blocked_signatures.add(_question_signature_from_model(existing_question))
            continue

        generated = candidate_generated
        break

    if not generated:
        return None

    ts = int(datetime.now(timezone.utc).timestamp())
    base_external_id = f"CG{subject_id}{topic_id}{user_id}{ts}"[-18:]
    external_id = f"{base_external_id}00"
    for suffix in range(100):
        candidate = f"{base_external_id}{suffix:02d}"[:20]
        exists = await db.execute(select(Question).where(Question.external_id == candidate))
        if not exists.scalar_one_or_none():
            external_id = candidate
            break

    question = Question(
        external_id=external_id,
        topic_id=topic_id,
        stem=generated["stem"],
        option_a=generated["option_a"],
        option_b=generated["option_b"],
        option_c=generated["option_c"],
        option_d=generated["option_d"],
        correct_answer=generated["correct_answer"],
        difficulty_b=generated["difficulty_b"],
        discrimination_a=generated["discrimination_a"],
        guessing_c=generated["guessing_c"],
        question_type=target_level,
        time_limit_seconds=90 if target_level == "Vận dụng" else 60,
        time_display="01:30" if target_level == "Vận dụng" else "01:00",
    )
    db.add(question)
    await db.flush()

    loaded_result = await db.execute(
        select(Question)
        .where(Question.id == question.id)
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    return loaded_result.scalar_one_or_none()


@router.post("/start-cat", response_model=CATStepOut)
async def start_cat_quiz(
    config: QuizConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start adaptive CAT session and return first optimal question."""
    settings = get_settings()
    query = (
        select(Question)
        .join(Topic)
        .join(MajorTopic)
        .where(MajorTopic.subject_id == config.subject_id)
        .where(Question.is_archived.is_(False))
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    if config.topic_ids:
        query = query.where(Question.topic_id.in_(config.topic_ids))

    result = await db.execute(query)
    pool = result.scalars().unique().all()

    session = QuizSession(
        user_id=user.id,
        subject_id=config.subject_id,
        total_questions=config.num_questions,
        theta_estimate=0,
    )
    db.add(session)
    await db.flush()

    if not pool:
        llm_runtime_settings = await get_effective_llm_runtime_config(db)
        start_topic_id = await _pick_start_topic_id_for_cat(db, config.subject_id, config.topic_ids)
        if start_topic_id is None:
            raise HTTPException(status_code=404, detail="No questions or topics found for this subject")

        generated_q = await _generate_and_persist_cat_question(
            db=db,
            user_id=user.id,
            subject_id=config.subject_id,
            topic_id=start_topic_id,
            theta=0.0,
            blocked_signatures=set(),
            llm_runtime_settings=llm_runtime_settings,
        )
        if not generated_q:
            raise HTTPException(status_code=404, detail="No questions found and LLM bootstrap failed")
        pool = [generated_q]

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

    recent_answered_ids = await _recent_answered_question_ids(
        db=db,
        user_id=user.id,
        subject_id=config.subject_id,
        window_size=int(settings.CAT_RECENT_QUESTION_WINDOW),
    )
    if recent_answered_ids:
        fresh_candidates = [q for q in candidate_dicts if q["id"] not in recent_answered_ids]
        if fresh_candidates:
            candidate_dicts = fresh_candidates

    # R1: Initialization rule (first item): pick b≈0 and a>1.2.
    r1_candidates = [
        q for q in candidate_dicts
        if abs(float(q["difficulty_b"])) <= 0.4 and float(q["discrimination_a"]) > 1.2
    ]
    next_q_dict = select_best_by_fisher(r1_candidates, current_theta=0.0)
    if not next_q_dict:
        opening_candidates = prioritize_high_discrimination(candidate_dicts, top_n=10)
        next_q_dict = select_best_by_fisher(opening_candidates, current_theta=0.0)
    if not next_q_dict:
        next_q_dict = select_next_adaptive(candidate_dicts, current_theta=0.0, answered_ids=set())
    if not next_q_dict:
        llm_runtime_settings = await get_effective_llm_runtime_config(db)
        start_topic_id = await _pick_start_topic_id_for_cat(db, config.subject_id, config.topic_ids)
        if start_topic_id is not None:
            generated_q = await _generate_and_persist_cat_question(
                db=db,
                user_id=user.id,
                subject_id=config.subject_id,
                topic_id=start_topic_id,
                theta=0.0,
                blocked_signatures=set(),
                llm_runtime_settings=llm_runtime_settings,
            )
            if generated_q:
                pool.append(generated_q)
                next_q_dict = {
                    "id": generated_q.id,
                    "difficulty_b": float(generated_q.difficulty_b),
                    "discrimination_a": float(generated_q.discrimination_a),
                }
    next_question = None
    if next_q_dict:
        next_question = next((q for q in pool if q.id == next_q_dict["id"]), None)

    await db.commit()

    return CATStepOut(
        session_id=session.id,
        question=_question_to_out(next_question) if next_question else None,
        theta=0.0,
        sem=999.0,
        answered_count=0,
        max_questions=config.num_questions,
        is_completed=False,
        bloom_classification=None,
        applied_rules=["R1"] if next_q_dict and any(
            q["id"] == next_q_dict["id"] and abs(float(q["difficulty_b"])) <= 0.4 and float(q["discrimination_a"]) > 1.2
            for q in candidate_dicts
        ) else [],
        theta_history=[0.0],
        recommendations=[],
    )


@router.post("/generate-question", response_model=GeneratedQuestionOut)
async def generate_question_with_llm(
    payload: LLMGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a new question draft and pre-label IRT params from topic context."""
    _ = user
    topic = await db.get(Topic, payload.topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    llm_runtime_settings = await get_effective_llm_runtime_config(db)

    generated = generate_question_from_topic(
        topic_name=topic.name,
        knowledge_context=payload.knowledge_context,
        target_level=payload.target_level,
        runtime_settings=llm_runtime_settings,
    )
    return GeneratedQuestionOut(**generated)


@router.get("/evaluation/difficulty-calibration", response_model=CalibrationReport)
async def difficulty_calibration_report(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Evaluate whether observed correctness aligns with difficulty parameter b."""
    _ = user
    result = await db.execute(
        select(QuizResponse)
        .options(selectinload(QuizResponse.question))
        .where(QuizResponse.user_answer.isnot(None))
    )
    responses = result.scalars().all()

    buckets = {
        "easy (b<-0.8)": [],
        "medium (-0.8<=b<=0.8)": [],
        "hard (b>0.8)": [],
    }

    for r in responses:
        b = float(r.question.difficulty_b)
        if b < -0.8:
            buckets["easy (b<-0.8)"].append(r)
        elif b > 0.8:
            buckets["hard (b>0.8)"].append(r)
        else:
            buckets["medium (-0.8<=b<=0.8)"].append(r)

    report_bins: list[CalibrationBin] = []
    for name, items in buckets.items():
        if not items:
            report_bins.append(
                CalibrationBin(
                    bucket=name,
                    count=0,
                    avg_b=0,
                    observed_accuracy=0,
                )
            )
            continue
        avg_b = sum(float(i.question.difficulty_b) for i in items) / len(items)
        observed = sum(1 for i in items if i.is_correct) / len(items)
        report_bins.append(
            CalibrationBin(
                bucket=name,
                count=len(items),
                avg_b=round(avg_b, 3),
                observed_accuracy=round(observed, 4),
            )
        )

    return CalibrationReport(total_responses=len(responses), bins=report_bins)


@router.post("/{session_id}/answer", response_model=CATStepOut)
async def answer_cat_question(
    session_id: int,
    payload: CATAnswerSubmit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit one CAT answer, update theta, and return next question or completion state."""
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session.completed_at:
        raise HTTPException(status_code=400, detail="Quiz already completed")

    q_result = await db.execute(
        select(Question)
        .where(Question.id == payload.question_id)
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    question = q_result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    major_topic = question.topic.major_topic if question.topic else None
    if not major_topic or major_topic.subject_id != session.subject_id:
        raise HTTPException(status_code=400, detail="Question is not in this quiz subject")

    existing_result = await db.execute(
        select(QuizResponse).where(
            QuizResponse.session_id == session_id,
            QuizResponse.question_id == payload.question_id,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Question already answered")

    is_correct = payload.user_answer.upper() == question.correct_answer.upper()
    guessing_suspected = is_correct and (payload.time_spent_seconds or 0) < 5 and float(question.guessing_c) > 0.25
    response_row = QuizResponse(
        session_id=session_id,
        question_id=payload.question_id,
        user_answer=payload.user_answer.upper(),
        is_correct=is_correct,
        guessing_flag=guessing_suspected,
        time_spent_seconds=payload.time_spent_seconds,
    )
    db.add(response_row)
    await db.flush()

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
        scoring_data.append(
            {
                "a": float(q.discrimination_a),
                "b": float(q.difficulty_b),
                "c": float(q.guessing_c),
                "is_correct": r.is_correct,
                "topic_id": q.topic_id,
                "topic_name": q.topic.name if q.topic else str(q.topic_id),
                "major_topic_name": q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
                "question_type": q.question_type,
                "is_sql": _is_sql_context(
                    q.topic.name if q.topic else "",
                    q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
                ),
                "guessing_flag": bool(r.guessing_flag),
                "difficulty_level": classify_difficulty_level(float(q.difficulty_b)),
            }
        )

    raw_theta = estimate_theta(scoring_data, initial_theta=float(session.theta_estimate or 0.0))
    # R6: If likely guessed, damp theta update to avoid over-inflation.
    if guessing_suspected:
        prev_theta = float(session.theta_estimate or 0.0)
        theta = prev_theta + 0.3 * (raw_theta - prev_theta)
    else:
        theta = raw_theta
    sem = standard_error_of_measurement(theta, scoring_data)
    answered_count = len(responses)
    max_questions = int(session.total_questions or 20)

    stop_reason = None
    is_completed = False
    if sem < 0.3:
        stop_reason = "SEM < 0.3"
        is_completed = True
    elif answered_count >= max_questions:
        stop_reason = "Đạt số câu tối đa"
        is_completed = True

    session.theta_estimate = theta
    session.correct_answers = sum(1 for r in responses if r.is_correct)

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
    bloom_classification = None
    applied_rules: list[str] = []
    rule_events: list[dict] = []
    recommendations: list[LearningRecommendation] = []

    if guessing_suspected:
        _append_rule(
            applied_rules,
            rule_events,
            "R6",
            "Correct < 5s with c > 0.25 => suspected guessing; damp theta update",
            question_id=payload.question_id,
        )
        recommendations.append(
            LearningRecommendation(
                topic_id=question.topic_id,
                topic_name=question.topic.name if question.topic else "",
                prerequisite_topic_id=None,
                prerequisite_topic_name=None,
                reason="Có khả năng đoán mò (đúng < 5 giây, c > 0.25) - giảm mức tăng theta",
            )
        )

    if is_completed:
        session.completed_at = datetime.now(timezone.utc)
        session.total_score = (session.correct_answers / answered_count) * 100 if answered_count > 0 else 0
        recommendations.extend(await _build_recommendations(db, responses))
        bloom_classification = _classify_bloom(theta, scoring_data)

        topic_scores = score_quiz(scoring_data).get("topic_scores", {})
        for tname, tscore in topic_scores.items():
            topic_id = None
            for sd in scoring_data:
                if sd["topic_name"] == tname:
                    topic_id = sd["topic_id"]
                    break
            if topic_id is None:
                continue

            prog_result = await db.execute(
                select(UserTopicProgress).where(
                    UserTopicProgress.user_id == user.id,
                    UserTopicProgress.topic_id == topic_id,
                )
            )
            progress = prog_result.scalar_one_or_none()
            if not progress:
                progress = UserTopicProgress(user_id=user.id, topic_id=topic_id)
                db.add(progress)

            progress.questions_attempted = (progress.questions_attempted or 0) + tscore["total"]
            progress.questions_correct = (progress.questions_correct or 0) + tscore["correct"]
            progress.theta_estimate = tscore["theta"]
            progress.mastery_level = tscore["mastery"]
    else:
        settings = get_settings()
        llm_runtime_settings = await get_effective_llm_runtime_config(db)
        answered_ids = {r.question_id for r in responses}
        answered_signatures = {_question_signature_from_model(r.question) for r in responses}
        recent_answered_ids = await _recent_answered_question_ids(
            db=db,
            user_id=user.id,
            subject_id=session.subject_id,
            window_size=int(settings.CAT_RECENT_QUESTION_WINDOW),
        )

        candidate_rows = await db.execute(
            select(
                Question.id,
                Question.topic_id,
                Question.question_type,
                Question.discrimination_a,
                Question.difficulty_b,
                Question.guessing_c,
                Topic.name.label("topic_name"),
                MajorTopic.name.label("major_topic_name"),
            )
            .select_from(Question)
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
                "topic_name": row.topic_name,
                "major_topic_name": row.major_topic_name,
                "is_sql": _is_sql_context(row.topic_name, row.major_topic_name),
            }
            for row in candidate_rows
        ]

        unanswered_fresh = [
            q for q in candidate_dicts
            if q["id"] not in answered_ids and q["id"] not in recent_answered_ids
        ]
        unanswered = unanswered_fresh if unanswered_fresh else [q for q in candidate_dicts if q["id"] not in answered_ids]
        min_gap = min((abs(float(q["difficulty_b"]) - float(theta)) for q in unanswered), default=99.0)

        # R2: Correct + previous type is Nhan biet => force next in same topic with Thong hieu.
        if is_correct and _normalize_question_type(question.question_type) == "nhan_biet":
            r2_candidates = [
                q for q in unanswered
                if q["topic_id"] == question.topic_id and _normalize_question_type(q.get("question_type")) == "thong_hieu"
            ]
            r2_pick = _pick_min_b_gap(r2_candidates, target_b=theta)
            if r2_pick:
                _append_rule(
                    applied_rules,
                    rule_events,
                    "R2",
                    "Correct Nhan biet => next Thong hieu in same topic",
                    question_id=int(r2_pick["id"]),
                )
                next_q_result = await db.execute(
                    select(Question)
                    .where(Question.id == r2_pick["id"])
                    .options(selectinload(Question.topic).selectinload(Topic.major_topic))
                )
                next_q = next_q_result.scalar_one_or_none()
                if next_q:
                    next_question_out = _question_to_out(next_q)

        # R5: Weak SQL (<50%) after >3 answers => easier SQL at theta-0.5.
        if not next_question_out and answered_count > 3 and _compute_sql_accuracy(scoring_data) < 0.5:
            target_b = float(theta) - 0.5
            r5_candidates = [
                q for q in unanswered
                if q.get("is_sql") and float(q["difficulty_b"]) <= target_b
            ]
            r5_pick = _pick_min_b_gap(r5_candidates, target_b=target_b)
            if r5_pick:
                _append_rule(
                    applied_rules,
                    rule_events,
                    "R5",
                    "SQL accuracy < 50% after >3 answers => easier SQL at theta-0.5",
                    question_id=int(r5_pick["id"]),
                )
                next_q_result = await db.execute(
                    select(Question)
                    .where(Question.id == r5_pick["id"])
                    .options(selectinload(Question.topic).selectinload(Topic.major_topic))
                )
                next_q = next_q_result.scalar_one_or_none()
                if next_q:
                    next_question_out = _question_to_out(next_q)

        # R4: If SQL ratio > 0.6, switch to non-SQL content.
        if not next_question_out and _compute_sql_ratio(scoring_data) > 0.6:
            r4_candidates = [q for q in unanswered if not q.get("is_sql")]
            r4_pick = _pick_min_b_gap(r4_candidates, target_b=theta)
            if r4_pick:
                _append_rule(
                    applied_rules,
                    rule_events,
                    "R4",
                    "SQL ratio > 0.6 => switch to non-SQL content",
                    question_id=int(r4_pick["id"]),
                )
                next_q_result = await db.execute(
                    select(Question)
                    .where(Question.id == r4_pick["id"])
                    .options(selectinload(Question.topic).selectinload(Topic.major_topic))
                )
                next_q = next_q_result.scalar_one_or_none()
                if next_q:
                    next_question_out = _question_to_out(next_q)

        # R3: Filter by rule-compatible difficulty band, then choose max Fisher information.
        if not next_question_out:
            r3_gap = min((abs(float(q["difficulty_b"]) - float(theta)) for q in unanswered), default=99.0)
            band = max(0.35, min(0.8, r3_gap + 0.2))
            r3_candidates = [
                q for q in unanswered
                if abs(float(q["difficulty_b"]) - float(theta)) <= band
            ]
            if answered_count < 4:
                prioritized = prioritize_high_discrimination(r3_candidates, top_n=10)
                if prioritized:
                    r3_candidates = prioritized

            r3_pick = select_best_by_fisher(r3_candidates, current_theta=float(theta))
            if r3_pick:
                reason = "Select next item by max Fisher info within rule-filtered difficulty band"
                if answered_count < 4:
                    reason = "Early CAT: prioritize high-a shortlist, then select max Fisher info within difficulty band"
                _append_rule(
                    applied_rules,
                    rule_events,
                    "R3",
                    reason,
                    question_id=int(r3_pick["id"]),
                )
                next_q_result = await db.execute(
                    select(Question)
                    .where(Question.id == r3_pick["id"])
                    .options(selectinload(Question.topic).selectinload(Topic.major_topic))
                )
                next_q = next_q_result.scalar_one_or_none()
                if next_q:
                    next_question_out = _question_to_out(next_q)

        # Hybrid Triggered by CAT: generate by LLM when no remaining item is close to target theta.
        # 0.45 is a practical threshold to avoid overusing LLM while still filling niche difficulty gaps.
        if (
            not next_question_out
            and llm_runtime_settings.get("cat_enable_hybrid_llm_on_answer")
            and min_gap > 0.45
        ):
            error_rates = topic_error_rates(scoring_data)
            preferred_topic_id = None
            if error_rates:
                preferred_topic_id = max(error_rates.items(), key=lambda kv: kv[1])[0]
            if preferred_topic_id is None and responses:
                preferred_topic_id = responses[-1].question.topic_id
            if preferred_topic_id is None and candidate_dicts:
                preferred_topic_id = candidate_dicts[0]["topic_id"]

            if preferred_topic_id is not None:
                generated_q = await _generate_and_persist_cat_question(
                    db=db,
                    user_id=user.id,
                    subject_id=session.subject_id,
                    topic_id=preferred_topic_id,
                    theta=float(theta),
                    blocked_signatures=answered_signatures,
                    llm_runtime_settings=llm_runtime_settings,
                )
                if generated_q:
                    next_question_out = _question_to_out(generated_q)

        # Safety fallback to Fisher info if no rule picked any question.
        if not next_question_out:
            next_q_dict = select_next_adaptive(candidate_dicts, current_theta=theta, answered_ids=answered_ids)
            if next_q_dict:
                next_q_result = await db.execute(
                    select(Question)
                    .where(Question.id == next_q_dict["id"])
                    .options(selectinload(Question.topic).selectinload(Topic.major_topic))
                )
                next_q = next_q_result.scalar_one_or_none()
                if next_q:
                    next_question_out = _question_to_out(next_q)
        if not next_question_out:
            is_completed = True
            stop_reason = "Hết câu hỏi phù hợp"
            session.completed_at = datetime.now(timezone.utc)
            session.total_score = (session.correct_answers / answered_count) * 100 if answered_count > 0 else 0
            recommendations.extend(await _build_recommendations(db, responses))
            bloom_classification = _classify_bloom(theta, scoring_data)

    if bloom_classification:
        _append_rule(
            applied_rules,
            rule_events,
            "R7",
            "Final theta > 1.5 and Van dung accuracy > 80%",
            question_id=next_question_out.id if next_question_out else None,
        )

    for event in rule_events:
        db.add(
            InferenceRuleLog(
                session_id=session_id,
                response_id=response_row.id,
                question_id=event["question_id"],
                rule_code=event["rule_code"],
                reason=event["reason"],
            )
        )

    await db.commit()

    return CATStepOut(
        session_id=session_id,
        question=next_question_out,
        theta=round(float(theta), 3),
        sem=round(float(sem), 3),
        answered_count=answered_count,
        max_questions=max_questions,
        is_completed=is_completed,
        stop_reason=stop_reason,
        bloom_classification=bloom_classification,
        applied_rules=applied_rules,
        theta_history=_theta_history_from_responses(responses),
        recommendations=recommendations,
    )


@router.post("/start", response_model=QuizSessionOut)
async def start_quiz(
    config: QuizConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a new quiz session with questions selected by knowledge structure."""
    # Get all questions for the subject
    query = (
        select(Question)
        .join(Topic)
        .join(MajorTopic)
        .where(MajorTopic.subject_id == config.subject_id)
        .where(Question.is_archived.is_(False))
    )
    result = await db.execute(query)
    all_questions = result.scalars().all()

    if not all_questions:
        raise HTTPException(status_code=404, detail="No questions found for this subject")

    # Convert to dicts for selector
    q_dicts = [
        {
            "id": q.id,
            "topic_id": q.topic_id,
            "question_type": q.question_type,
            "difficulty_b": float(q.difficulty_b),
            "discrimination_a": float(q.discrimination_a),
            "guessing_c": float(q.guessing_c),
        }
        for q in all_questions
    ]

    selected = select_quiz_questions(
        q_dicts,
        num_questions=config.num_questions,
        recognition_pct=config.recognition_pct,
        comprehension_pct=config.comprehension_pct,
        application_pct=config.application_pct,
        topic_ids=config.topic_ids,
    )

    # Create session
    session = QuizSession(
        user_id=user.id,
        subject_id=config.subject_id,
        total_questions=len(selected),
    )
    db.add(session)
    await db.flush()

    # Pre-create empty responses to track question order
    for q_dict in selected:
        response = QuizResponse(
            session_id=session.id,
            question_id=q_dict["id"],
            is_correct=False,
        )
        db.add(response)

    await db.commit()
    await db.refresh(session)

    return QuizSessionOut(
        id=session.id,
        subject_id=session.subject_id,
        total_questions=session.total_questions,
    )


@router.get("/{session_id}/questions", response_model=list[QuestionOut])
async def get_quiz_questions(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get questions for an active quiz session (without answers)."""
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .options(
            selectinload(QuizResponse.question)
            .selectinload(Question.topic)
            .selectinload(Topic.major_topic)
        )
    )
    responses = result.scalars().all()

    questions = []
    for r in responses:
        q = r.question
        questions.append(QuestionOut(
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
        ))

    return questions


@router.post("/{session_id}/submit")
async def submit_answers(
    session_id: int,
    answers: list[AnswerSubmit],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit all answers for a quiz session."""
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if session.completed_at:
        raise HTTPException(status_code=400, detail="Quiz already completed")

    # Get responses
    result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .options(
            selectinload(QuizResponse.question)
            .selectinload(Question.topic)
            .selectinload(Topic.major_topic)
        )
    )
    db_responses = {r.question_id: r for r in result.scalars().all()}

    # Map answers
    answer_map = {a.question_id: a for a in answers}

    scoring_data = []
    for qid, resp in db_responses.items():
        q = resp.question
        user_ans = answer_map.get(qid)
        if user_ans:
            resp.user_answer = user_ans.user_answer
            resp.is_correct = user_ans.user_answer.upper() == q.correct_answer.upper()
            resp.time_spent_seconds = user_ans.time_spent_seconds
            resp.guessing_flag = bool(resp.is_correct and (user_ans.time_spent_seconds or 0) < 5 and float(q.guessing_c) > 0.25)
        else:
            resp.is_correct = False
            resp.guessing_flag = False

        scoring_data.append({
            "a": float(q.discrimination_a),
            "b": float(q.difficulty_b),
            "c": float(q.guessing_c),
            "is_correct": resp.is_correct,
            "guessing_flag": bool(resp.guessing_flag),
            "question_type": q.question_type,
            "topic_id": q.topic_id,
            "topic_name": q.topic.name if q.topic else str(q.topic_id),
            "major_topic_name": q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            "is_sql": _is_sql_context(
                q.topic.name if q.topic else "",
                q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            ),
        })

    # Score
    score_result = score_quiz(scoring_data)

    # Update session
    session.completed_at = datetime.now(timezone.utc)
    session.correct_answers = score_result["score"]
    session.total_score = score_result["accuracy"] * 100
    session.theta_estimate = score_result["theta"]

    # Update user topic progress
    for tname, tscore in score_result["topic_scores"].items():
        # Find topic id from scoring data
        topic_id = None
        for sd in scoring_data:
            if sd["topic_name"] == tname:
                topic_id = sd["topic_id"]
                break
        if topic_id is None:
            continue

        # Upsert progress
        prog_result = await db.execute(
            select(UserTopicProgress).where(
                UserTopicProgress.user_id == user.id,
                UserTopicProgress.topic_id == topic_id,
            )
        )
        progress = prog_result.scalar_one_or_none()
        if not progress:
            progress = UserTopicProgress(
                user_id=user.id, topic_id=topic_id
            )
            db.add(progress)

        progress.questions_attempted = (progress.questions_attempted or 0) + tscore["total"]
        progress.questions_correct = (progress.questions_correct or 0) + tscore["correct"]
        progress.theta_estimate = tscore["theta"]
        progress.mastery_level = tscore["mastery"]

    await db.commit()

    bloom_classification = _classify_bloom(float(score_result["theta"]), scoring_data)

    return {
        "message": "Quiz submitted successfully",
        "score": score_result["score"],
        "total": score_result["total"],
        "accuracy": score_result["accuracy"],
        "theta": score_result["theta"],
        "mastery": score_result["mastery"],
        "bloom_classification": bloom_classification,
    }


@router.get("/{session_id}/results", response_model=QuizResultOut)
async def get_quiz_results(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get detailed results for a completed quiz."""
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    # Get subject name
    subject = await db.get(Subject, session.subject_id)

    result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .options(
            selectinload(QuizResponse.question)
            .selectinload(Question.topic)
            .selectinload(Topic.major_topic)
        )
    )
    responses = result.scalars().all()

    results = []
    topic_scores = {}

    for r in responses:
        q = r.question
        tname = q.topic.name if q.topic else "Unknown"

        if tname not in topic_scores:
            topic_scores[tname] = {"correct": 0, "total": 0, "mastery": "beginner"}
        topic_scores[tname]["total"] += 1
        if r.is_correct:
            topic_scores[tname]["correct"] += 1

        results.append(QuizResultDetail(
            question=QuestionWithAnswer(
                id=q.id,
                external_id=q.external_id,
                stem=q.stem,
                option_a=q.option_a,
                option_b=q.option_b,
                option_c=q.option_c,
                option_d=q.option_d,
                correct_answer=q.correct_answer,
                difficulty_b=float(q.difficulty_b),
                discrimination_a=float(q.discrimination_a),
                guessing_c=float(q.guessing_c),
                question_type=q.question_type,
                time_limit_seconds=q.time_limit_seconds,
                time_display=q.time_display,
                topic_name=tname,
                major_topic_name=q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            ),
            user_answer=r.user_answer,
            is_correct=r.is_correct,
            time_spent_seconds=r.time_spent_seconds or 0,
        ))

    session_out = QuizSessionOut(
        id=session.id,
        subject_id=session.subject_id,
        subject_name=subject.name if subject else "",
        total_questions=session.total_questions or 0,
        correct_answers=session.correct_answers or 0,
        total_score=float(session.total_score) if session.total_score else None,
        theta_estimate=float(session.theta_estimate) if session.theta_estimate else None,
        started_at=session.started_at.isoformat() if session.started_at else None,
        completed_at=session.completed_at.isoformat() if session.completed_at else None,
    )

    return QuizResultOut(
        session=session_out,
        results=results,
        topic_scores=topic_scores,
    )


@router.get("/{session_id}/rule-logs", response_model=list[InferenceRuleLogOut])
async def get_session_rule_logs(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get inference rule audit logs for a quiz session."""
    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")

    responses_result = await db.execute(
        select(QuizResponse.id)
        .where(QuizResponse.session_id == session_id)
        .order_by(QuizResponse.id.asc())
    )
    response_ids = [row.id for row in responses_result]
    step_map = {rid: idx + 1 for idx, rid in enumerate(response_ids)}

    logs_result = await db.execute(
        select(InferenceRuleLog, Question.external_id, Question.stem, QuizResponse.answered_at)
        .outerjoin(Question, Question.id == InferenceRuleLog.question_id)
        .outerjoin(QuizResponse, QuizResponse.id == InferenceRuleLog.response_id)
        .where(InferenceRuleLog.session_id == session_id)
        .order_by(InferenceRuleLog.id.asc())
    )
    rows = logs_result.all()

    return [
        InferenceRuleLogOut(
            id=log.id,
            session_id=log.session_id,
            response_id=log.response_id,
            step_index=step_map.get(log.response_id) if log.response_id is not None else None,
            question_id=log.question_id,
            question_external_id=external_id,
            question_stem=stem,
            rule_code=log.rule_code,
            reason=log.reason,
            answered_at=answered_at.isoformat() if answered_at else None,
            created_at=log.created_at.isoformat() if log.created_at else None,
        )
        for log, external_id, stem, answered_at in rows
    ]
