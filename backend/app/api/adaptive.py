"""Exam-batch adaptive testing API (multi-stage testing).

Flow: POST /start creates a chain + exam #1 -> user answers the whole exam ->
POST /{chain_id}/submit grades it, updates cumulative theta/sem and decides
whether to stop -> POST /{chain_id}/next generates the next rule-driven exam
-> ... -> GET /{chain_id}/summary aggregates the whole chain.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.api.auth import get_current_user
from app.config import get_settings
from app.models.user import User, ExamChain, QuizSession, QuizResponse, UserTopicProgress, InferenceRuleLog
from app.models.question import Question
from app.models.knowledge import Topic, Subject
from app.models.cat_knowledge import UserAbility
from app.schemas.question import (
    AdaptiveStartConfig,
    AdaptiveExamOut,
    AdaptiveSubmitIn,
    ExamEvaluationOut,
    ChainExamRow,
    ChainStateOut,
    ChainSummaryOut,
    LearningRecommendation,
)
from app.engine.irt import estimate_ability_3pl
from app.engine.scoring import score_quiz
from app.services.runtime_settings import get_effective_llm_runtime_config
from app.services.adaptive_shared import (
    build_recommendations,
    build_scoring_data,
    classify_bloom,
    question_signature_from_model,
    question_to_out,
    safe_numeric,
    theta_history_from_scoring_data,
)
from app.services.exam_generation import generate_exam

router = APIRouter(prefix="/api/quiz/adaptive", tags=["adaptive"])


async def _get_chain_or_404(db: AsyncSession, chain_id: int, user: User) -> ExamChain:
    chain = await db.get(ExamChain, chain_id)
    if not chain or chain.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam chain not found")
    return chain


async def _chain_sessions(db: AsyncSession, chain_id: int) -> list[QuizSession]:
    result = await db.execute(
        select(QuizSession)
        .where(QuizSession.chain_id == chain_id)
        .order_by(QuizSession.exam_index.asc(), QuizSession.id.asc())
    )
    return list(result.scalars().all())


async def _session_responses(db: AsyncSession, session_id: int) -> list[QuizResponse]:
    result = await db.execute(
        select(QuizResponse)
        .where(QuizResponse.session_id == session_id)
        .order_by(QuizResponse.id.asc())
        .options(
            selectinload(QuizResponse.question)
            .selectinload(Question.topic)
            .selectinload(Topic.major_topic)
        )
    )
    return list(result.scalars().all())


async def _completed_chain_responses(
    db: AsyncSession, chain_id: int, include_session_id: int | None = None
) -> list[QuizResponse]:
    """All responses of the chain's completed exams, in exam order.

    include_session_id lets the submit flow include the exam being graded
    before its completed_at is flushed.
    """
    condition = QuizSession.completed_at.isnot(None)
    if include_session_id is not None:
        condition = condition | (QuizSession.id == include_session_id)

    result = await db.execute(
        select(QuizResponse)
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .where(QuizSession.chain_id == chain_id)
        .where(condition)
        .order_by(QuizSession.exam_index.asc(), QuizResponse.id.asc())
        .options(
            selectinload(QuizResponse.question)
            .selectinload(Question.topic)
            .selectinload(Topic.major_topic)
        )
    )
    return list(result.scalars().all())


async def _all_chain_question_ids(db: AsyncSession, chain_id: int) -> set[int]:
    result = await db.execute(
        select(QuizResponse.question_id)
        .join(QuizSession, QuizSession.id == QuizResponse.session_id)
        .where(QuizSession.chain_id == chain_id)
    )
    return {row.question_id for row in result}


def _exam_out(
    chain: ExamChain,
    session: QuizSession,
    questions: list[Question],
    applied_rules: list[str],
) -> AdaptiveExamOut:
    return AdaptiveExamOut(
        chain_id=chain.id,
        session_id=session.id,
        exam_index=int(session.exam_index or 1),
        max_exams=int(chain.max_exams or 5),
        questions_per_exam=int(chain.questions_per_exam or len(questions)),
        questions=[question_to_out(q) for q in questions],
        theta=safe_numeric(chain.current_theta, default=0.0, min_value=-999.0, max_value=999.0),
        sem=safe_numeric(chain.current_sem, default=999.0, min_value=0.0, max_value=999.0),
        applied_rules=applied_rules,
        strategy=chain.strategy or "rules",
    )


def _persist_rule_events(
    db: AsyncSession,
    session_id: int,
    rule_events: list[dict],
    response_id_by_question: dict[int, int] | None = None,
):
    for event in rule_events:
        response_id = None
        if response_id_by_question and event.get("question_id") is not None:
            response_id = response_id_by_question.get(int(event["question_id"]))
        db.add(
            InferenceRuleLog(
                session_id=session_id,
                response_id=response_id,
                question_id=event.get("question_id"),
                rule_code=event["rule_code"],
                reason=event["reason"],
            )
        )


async def _complete_chain(db: AsyncSession, chain: ExamChain, stop_reason: str):
    chain.status = "completed"
    chain.stop_reason = stop_reason
    chain.completed_at = datetime.now(timezone.utc)


async def _create_exam_session(
    db: AsyncSession,
    chain: ExamChain,
    user: User,
    exam_index: int,
    questions: list[Question],
    rule_events: list[dict],
) -> QuizSession:
    session = QuizSession(
        user_id=user.id,
        subject_id=chain.subject_id,
        chain_id=chain.id,
        exam_index=exam_index,
        total_questions=len(questions),
        theta_estimate=safe_numeric(chain.current_theta, default=0.0, min_value=-999.0, max_value=999.0, ndigits=2),
    )
    db.add(session)
    await db.flush()

    for q in questions:
        db.add(QuizResponse(session_id=session.id, question_id=q.id, is_correct=False))

    _persist_rule_events(db, session.id, rule_events)
    chain.exams_generated = exam_index
    return session


@router.post("/start", response_model=AdaptiveExamOut)
async def start_adaptive_test(
    config: AdaptiveStartConfig,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create an exam chain and generate exam #1 using the R1 blueprint."""
    settings = get_settings()

    subject = await db.get(Subject, config.subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chain = ExamChain(
        user_id=user.id,
        subject_id=config.subject_id,
        questions_per_exam=max(1, min(int(config.questions_per_exam), 50)),
        max_exams=max(1, min(int(config.max_exams or settings.ADAPTIVE_MAX_EXAMS_DEFAULT), 10)),
        recognition_pct=config.recognition_pct,
        comprehension_pct=config.comprehension_pct,
        application_pct=config.application_pct,
        status="active",
        strategy="rl" if config.strategy == "rl" else "rules",
        current_theta=0,
        current_sem=999,
    )
    db.add(chain)
    await db.flush()

    llm_runtime_settings = await get_effective_llm_runtime_config(db)
    questions, rule_events = await generate_exam(
        db,
        chain=chain,
        user_id=user.id,
        exam_index=1,
        theta=0.0,
        sem=999.0,
        chain_scoring_data=[],
        prev_exam_scoring_data=[],
        used_question_ids=set(),
        used_signatures=set(),
        llm_runtime_settings=llm_runtime_settings,
    )
    if not questions:
        await db.rollback()
        raise HTTPException(status_code=404, detail="No questions found for this subject")

    session = await _create_exam_session(db, chain, user, 1, questions, rule_events)
    await db.commit()

    return _exam_out(chain, session, questions, [e["rule_code"] for e in rule_events])


@router.post("/{chain_id}/submit", response_model=ExamEvaluationOut)
async def submit_exam(
    chain_id: int,
    payload: AdaptiveSubmitIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Grade a whole exam, update cumulative theta/sem and decide stopping."""
    settings = get_settings()
    chain = await _get_chain_or_404(db, chain_id, user)

    session = await db.get(QuizSession, payload.session_id)
    if not session or session.chain_id != chain.id or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Exam session not found in this chain")

    already_completed = session.completed_at is not None
    applied_rules: list[str] = []
    rule_events: list[dict] = []
    recommendations: list[LearningRecommendation] = []

    responses = await _session_responses(db, session.id)
    response_id_by_question = {r.question_id: r.id for r in responses}

    if not already_completed:
        answer_map = {a.question_id: a for a in payload.answers}
        for resp in responses:
            q = resp.question
            user_ans = answer_map.get(resp.question_id)
            if user_ans and (user_ans.user_answer or "").strip():
                resp.user_answer = user_ans.user_answer.strip().upper()[:1]
                resp.is_correct = resp.user_answer == q.correct_answer.upper()
                resp.time_spent_seconds = user_ans.time_spent_seconds
                # R7: guessing suspicion (correct too fast on a guessable item)
                resp.guessing_flag = bool(
                    resp.is_correct
                    and (user_ans.time_spent_seconds or 0) < 10
                    and float(q.guessing_c) > 0.2
                )
            else:
                resp.user_answer = None
                resp.is_correct = False
                resp.guessing_flag = False
        await db.flush()

    for resp in responses:
        if resp.guessing_flag:
            if "R7" not in applied_rules:
                applied_rules.append("R7")
            rule_events.append(
                {
                    "rule_code": "R7",
                    "reason": "Đúng < 10s với c > 0.2 => nghi ngờ đoán mò; giảm trọng số cập nhật θ",
                    "question_id": resp.question_id,
                }
            )
            recommendations.append(
                LearningRecommendation(
                    topic_id=resp.question.topic_id,
                    topic_name=resp.question.topic.name if resp.question.topic else "",
                    reason="Có khả năng đoán mò (đúng < 10 giây, c > 0.2) - giảm mức tăng theta",
                )
            )

    exam_scoring_data = build_scoring_data(responses)
    exam_score = score_quiz(exam_scoring_data)

    # Cumulative ability over the whole chain (R7 damping preserved).
    chain_responses = await _completed_chain_responses(db, chain.id, include_session_id=session.id)
    chain_scoring_data = build_scoring_data(chain_responses)
    theta_history = theta_history_from_scoring_data(chain_scoring_data)
    theta = theta_history[-1] if theta_history else 0.0
    ability = estimate_ability_3pl(chain_scoring_data)
    sem = safe_numeric(ability["posterior_sd"], default=999.0, min_value=0.0, max_value=999.0)

    if not already_completed:
        prev_chain_sem = safe_numeric(chain.current_sem, default=999.0, min_value=0.0, max_value=999.0)

        session.completed_at = datetime.now(timezone.utc)
        session.correct_answers = exam_score["score"]
        session.total_score = exam_score["accuracy"] * 100
        session.theta_estimate = safe_numeric(theta, default=0.0, min_value=-999.0, max_value=999.0, ndigits=2)

        chain.current_theta = safe_numeric(theta, default=0.0, min_value=-999.0, max_value=999.0)
        chain.current_sem = sem

        # RL: reward the pending bandit decision with the SEM reduction
        # (information gained) obtained by this exam.
        if (chain.strategy or "rules") == "rl" and chain.rl_state is not None and chain.rl_action is not None:
            from app.services.rl_service import apply_reward

            reward = min(prev_chain_sem, 1.5) - float(sem)
            new_q = await apply_reward(
                db, chain.subject_id, chain.rl_state, int(chain.rl_action), reward
            )
            if "RL" not in applied_rules:
                applied_rules.append("RL")
            rule_events.append(
                {
                    "rule_code": "RL",
                    "reason": (
                        f"Bandit reward = ΔSEM = {reward:+.3f} cho state={chain.rl_state}, "
                        f"action={chain.rl_action} => Q = {new_q:.3f}"
                    ),
                    "question_id": None,
                }
            )
            chain.rl_state = None
            chain.rl_action = None

        # Upsert subject-level ability
        ability_result = await db.execute(
            select(UserAbility).where(
                UserAbility.user_id == user.id,
                UserAbility.subject_id == chain.subject_id,
            )
        )
        user_ability = ability_result.scalar_one_or_none()
        if not user_ability:
            user_ability = UserAbility(user_id=user.id, subject_id=chain.subject_id)
            db.add(user_ability)
        user_ability.theta_estimate = safe_numeric(theta, default=0.0, min_value=-999.0, max_value=999.0)
        user_ability.sem = sem
        user_ability.answered_count = len(chain_scoring_data)

        # Upsert per-topic progress from this exam's scores
        for tname, tscore in exam_score["topic_scores"].items():
            topic_id = next(
                (sd["topic_id"] for sd in exam_scoring_data if sd["topic_name"] == tname),
                None,
            )
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
            progress.theta_estimate = safe_numeric(
                tscore.get("theta"), default=0.0, min_value=-999.0, max_value=999.0, ndigits=2
            )
            progress.mastery_level = tscore["mastery"]

    # ---------- Stopping decision ----------
    chain_completed = chain.status == "completed"
    stop_reason = chain.stop_reason
    exam_index = int(session.exam_index or 1)
    if not chain_completed:
        if sem < float(settings.ADAPTIVE_SEM_STOP):
            await _complete_chain(db, chain, f"SEM < {settings.ADAPTIVE_SEM_STOP}")
            chain_completed, stop_reason = True, chain.stop_reason
        elif exam_index >= int(chain.max_exams or 1):
            await _complete_chain(db, chain, "Đạt số đề tối đa")
            chain_completed, stop_reason = True, chain.stop_reason

    bloom_classification = classify_bloom(theta, chain_scoring_data)
    if chain_completed:
        recommendations.extend(await build_recommendations(db, chain_responses))
        if bloom_classification and "BLOOM" not in applied_rules:
            applied_rules.append("BLOOM")
            rule_events.append(
                {
                    "rule_code": "BLOOM",
                    "reason": "θ cuối > 1.5 và độ chính xác Vận dụng > 80%: năng lực nổi trội",
                    "question_id": None,
                }
            )

    if not already_completed:
        _persist_rule_events(db, session.id, rule_events, response_id_by_question)
        await db.commit()

    return ExamEvaluationOut(
        chain_id=chain.id,
        session_id=session.id,
        exam_index=exam_index,
        max_exams=int(chain.max_exams or 1),
        score=int(exam_score["score"]),
        total=int(exam_score.get("total", len(responses))),
        accuracy=float(exam_score["accuracy"]),
        theta=round(float(theta), 3),
        sem=sem,
        theta_history=theta_history,
        applied_rules=applied_rules,
        topic_scores=exam_score["topic_scores"],
        bloom_classification=bloom_classification,
        recommendations=recommendations,
        chain_completed=chain_completed,
        stop_reason=stop_reason,
    )


@router.post("/{chain_id}/next", response_model=ChainStateOut)
async def next_exam(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Evaluate chain state and generate the next rule-driven exam."""
    chain = await _get_chain_or_404(db, chain_id, user)
    if chain.status != "active":
        return await _chain_state(db, chain)

    sessions = await _chain_sessions(db, chain.id)
    latest = sessions[-1] if sessions else None

    # Resume path: an unsubmitted exam already exists.
    if latest and latest.completed_at is None:
        return await _chain_state(db, chain)

    exam_index = (int(latest.exam_index or 0) if latest else 0) + 1
    if exam_index > int(chain.max_exams or 1):
        await _complete_chain(db, chain, "Đạt số đề tối đa")
        await db.commit()
        return await _chain_state(db, chain)

    chain_responses = await _completed_chain_responses(db, chain.id)
    chain_scoring_data = build_scoring_data(chain_responses)
    prev_scoring_data = build_scoring_data(
        [r for r in chain_responses if latest and r.session_id == latest.id]
    )
    used_question_ids = await _all_chain_question_ids(db, chain.id)
    used_signatures = {question_signature_from_model(r.question) for r in chain_responses}

    llm_runtime_settings = await get_effective_llm_runtime_config(db)
    theta = safe_numeric(chain.current_theta, default=0.0, min_value=-999.0, max_value=999.0)
    sem = safe_numeric(chain.current_sem, default=999.0, min_value=0.0, max_value=999.0)

    # RL strategy: a contextual bandit picks the difficulty offset for the
    # next exam instead of the fixed R2/R3 steps.
    b_target_override = None
    rl_event = None
    if (chain.strategy or "rules") == "rl" and prev_scoring_data:
        from app.engine.rl_policy import ACTIONS
        from app.services.rl_service import load_policy

        policy = await load_policy(db, chain.subject_id)
        prev_acc = sum(1 for r in prev_scoring_data if r["is_correct"]) / len(prev_scoring_data)
        state = policy.state_key(prev_acc, sem)
        action = policy.select_action(state)
        b_target_override = max(-3.0, min(3.0, theta + ACTIONS[action]))
        chain.rl_state = state
        chain.rl_action = action
        rl_event = {
            "rule_code": "RL",
            "reason": (
                f"Bandit state={state} chọn offset {ACTIONS[action]:+.1f} "
                f"=> b_target = {b_target_override:.2f} (thay cho R2/R3)"
            ),
            "question_id": None,
        }

    questions, rule_events = await generate_exam(
        db,
        chain=chain,
        user_id=user.id,
        exam_index=exam_index,
        theta=theta,
        sem=sem,
        chain_scoring_data=chain_scoring_data,
        prev_exam_scoring_data=prev_scoring_data,
        used_question_ids=used_question_ids,
        used_signatures=used_signatures,
        llm_runtime_settings=llm_runtime_settings,
        b_target_override=b_target_override,
    )
    if rl_event is not None:
        rule_events.insert(0, rl_event)
    if not questions:
        await _complete_chain(db, chain, "Hết câu hỏi phù hợp")
        await db.commit()
        return await _chain_state(db, chain)

    session = await _create_exam_session(db, chain, user, exam_index, questions, rule_events)
    await db.commit()

    return ChainStateOut(
        chain_id=chain.id,
        status=chain.status,
        stop_reason=chain.stop_reason,
        exam_index=exam_index,
        max_exams=int(chain.max_exams or 1),
        theta=theta,
        sem=sem,
        active_exam=_exam_out(chain, session, questions, [e["rule_code"] for e in rule_events]),
    )


async def _chain_state(db: AsyncSession, chain: ExamChain) -> ChainStateOut:
    sessions = await _chain_sessions(db, chain.id)
    latest = sessions[-1] if sessions else None

    active_exam = None
    if chain.status == "active" and latest and latest.completed_at is None:
        responses = await _session_responses(db, latest.id)
        rule_rows = await db.execute(
            select(InferenceRuleLog.rule_code)
            .where(InferenceRuleLog.session_id == latest.id)
            .order_by(InferenceRuleLog.id.asc())
        )
        applied_rules = list(dict.fromkeys(row.rule_code for row in rule_rows))
        active_exam = _exam_out(chain, latest, [r.question for r in responses], applied_rules)

    return ChainStateOut(
        chain_id=chain.id,
        status=chain.status,
        stop_reason=chain.stop_reason,
        exam_index=int(latest.exam_index or 0) if latest else 0,
        max_exams=int(chain.max_exams or 1),
        theta=safe_numeric(chain.current_theta, default=0.0, min_value=-999.0, max_value=999.0),
        sem=safe_numeric(chain.current_sem, default=999.0, min_value=0.0, max_value=999.0),
        active_exam=active_exam,
    )


@router.get("/rl-policy")
async def get_rl_policy(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Learned Q-table of the exam-difficulty bandit for a subject."""
    _ = user
    from app.services.rl_service import policy_snapshot

    return {"subject_id": subject_id, "policy": await policy_snapshot(db, subject_id)}


@router.get("/{chain_id}", response_model=ChainStateOut)
async def get_chain_state(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Current chain state, including the unsubmitted exam if any (resume)."""
    chain = await _get_chain_or_404(db, chain_id, user)
    return await _chain_state(db, chain)


@router.post("/{chain_id}/finish", response_model=ChainSummaryOut)
async def finish_chain(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """User-initiated finish: close the chain and drop an untouched pending exam."""
    chain = await _get_chain_or_404(db, chain_id, user)

    if chain.status == "active":
        sessions = await _chain_sessions(db, chain.id)
        latest = sessions[-1] if sessions else None
        if latest and latest.completed_at is None:
            answered = await db.execute(
                select(QuizResponse.id)
                .where(QuizResponse.session_id == latest.id)
                .where(QuizResponse.user_answer.isnot(None))
                .limit(1)
            )
            if answered.first() is None:
                # Untouched pending exam: remove it together with its logs.
                await db.execute(
                    delete(InferenceRuleLog).where(InferenceRuleLog.session_id == latest.id)
                )
                await db.execute(
                    delete(QuizResponse).where(QuizResponse.session_id == latest.id)
                )
                await db.execute(delete(QuizSession).where(QuizSession.id == latest.id))
                chain.exams_generated = max(0, int(chain.exams_generated or 1) - 1)
        await _complete_chain(db, chain, "Người dùng kết thúc")
        await db.commit()

    return await _chain_summary(db, chain)


@router.get("/{chain_id}/summary", response_model=ChainSummaryOut)
async def get_chain_summary(
    chain_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chain = await _get_chain_or_404(db, chain_id, user)
    return await _chain_summary(db, chain)


async def _chain_summary(db: AsyncSession, chain: ExamChain) -> ChainSummaryOut:
    subject = await db.get(Subject, chain.subject_id)
    sessions = await _chain_sessions(db, chain.id)

    exams = [
        ChainExamRow(
            session_id=s.id,
            exam_index=int(s.exam_index or 0),
            score=int(s.correct_answers or 0),
            total=int(s.total_questions or 0),
            accuracy=round(
                float(s.correct_answers or 0) / float(s.total_questions or 1), 4
            )
            if (s.total_questions or 0) > 0
            else 0.0,
            theta_after=float(s.theta_estimate) if s.theta_estimate is not None else None,
            completed=s.completed_at is not None,
        )
        for s in sessions
    ]

    chain_responses = await _completed_chain_responses(db, chain.id)
    chain_scoring_data = build_scoring_data(chain_responses)
    theta_history = theta_history_from_scoring_data(chain_scoring_data)
    theta = safe_numeric(chain.current_theta, default=0.0, min_value=-999.0, max_value=999.0)
    sem = safe_numeric(chain.current_sem, default=999.0, min_value=0.0, max_value=999.0)

    aggregate = score_quiz(chain_scoring_data) if chain_scoring_data else {"topic_scores": {}}
    recommendations = await build_recommendations(db, chain_responses)

    return ChainSummaryOut(
        chain_id=chain.id,
        subject_id=chain.subject_id,
        subject_name=subject.name if subject else "",
        status=chain.status,
        stop_reason=chain.stop_reason,
        theta=theta,
        sem=sem,
        total_questions=len(chain_scoring_data),
        total_correct=sum(1 for r in chain_scoring_data if r["is_correct"]),
        theta_history=theta_history,
        exams=exams,
        topic_scores=aggregate.get("topic_scores", {}),
        bloom_classification=classify_bloom(theta, chain_scoring_data),
        recommendations=recommendations,
    )
