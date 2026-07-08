"""Quiz API: Create quiz, submit answers, get results."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User, QuizSession, QuizResponse, UserTopicProgress, InferenceRuleLog
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic, Subject
from app.schemas.question import (
    QuizConfig, QuestionOut, QuizSessionOut, AnswerSubmit,
    QuizResultOut, QuizResultDetail, QuestionWithAnswer,
    LLMGenerateRequest, GeneratedQuestionOut,
    CalibrationReport, CalibrationBin, InferenceRuleLogOut,
)
from app.engine.question_selector import select_quiz_questions
from app.engine.scoring import score_quiz
from app.engine.irt import estimate_ability_3pl, classify_mastery
from app.engine.llm_generation import generate_question_from_topic
from app.services.runtime_settings import get_effective_llm_runtime_config
from app.services.adaptive_shared import (
    safe_numeric as _safe_numeric,
    normalize_text as _normalize_text,
    question_signature_from_payload as _question_signature_from_payload,
    question_signature_from_model as _question_signature_from_model,
    is_sql_context as _is_sql_context,
    classify_bloom as _classify_bloom,
)

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


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

    existing_rows = await db.execute(
        select(Question)
        .where(Question.topic_id == payload.topic_id)
        .order_by(Question.id.desc())
        .limit(500)
    )
    existing_questions = existing_rows.scalars().all()
    blocked_signatures = {_question_signature_from_model(q) for q in existing_questions}
    blocked_stems = {_normalize_text(q.stem) for q in existing_questions}

    existing_stem_samples = [
        f"- {q.stem.strip()[:140]}"
        for q in existing_questions[:8]
        if (q.stem or "").strip()
    ]
    base_context = (payload.knowledge_context or "").strip()

    generated = None
    for attempt in range(5):
        anti_dup_context = base_context
        if existing_stem_samples:
            anti_dup_context = (
                f"{anti_dup_context}\n\n" if anti_dup_context else ""
            ) + (
                "Yêu cầu chống trùng lặp: câu hỏi mới KHÔNG được trùng hoặc diễn đạt lại quá giống các stem sau:\n"
                + "\n".join(existing_stem_samples)
                + f"\nLần thử: {attempt + 1}."
            )

        candidate = generate_question_from_topic(
            topic_name=topic.name,
            knowledge_context=anti_dup_context or payload.knowledge_context,
            target_level=payload.target_level,
            runtime_settings=llm_runtime_settings,
        )

        candidate_signature = _question_signature_from_payload(candidate)
        candidate_stem = _normalize_text(candidate.get("stem", ""))
        if candidate_signature in blocked_signatures or candidate_stem in blocked_stems:
            continue

        generated = candidate
        break

    if not generated:
        raise HTTPException(
            status_code=409,
            detail="Không thể sinh câu hỏi mới không trùng với ngân hàng hiện tại cho topic này",
        )

    return GeneratedQuestionOut(**generated)


@router.get("/evaluation/convergence")
async def convergence_report(
    subject_id: int,
    n_students: int = 20,
    questions_per_exam: int = 6,
    max_exams: int = 5,
    seed: int = 42,
    include_rl: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Simulation study: bias/RMSE/correlation/SEM convergence of the
    adaptive engine vs. fisher-optimal and random selection baselines.
    include_rl adds a bandit strategy that learns across the simulated
    students (fresh Q-table, not the production one)."""
    _ = user
    from app.evaluation.convergence import run_convergence_study
    from app.engine.rl_policy import QTable

    strategies = ("rules", "fisher", "random") + (("rl",) if include_rl else ())
    try:
        return await run_convergence_study(
            db,
            subject_id,
            n_students=max(5, min(int(n_students), 60)),
            questions_per_exam=max(3, min(int(questions_per_exam), 20)),
            max_exams=max(1, min(int(max_exams), 8)),
            seed=int(seed),
            strategies=strategies,
            policy=QTable(seed=int(seed)) if include_rl else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/dkt/train")
async def train_dkt_model(
    subject_id: int,
    synthetic_students: int = 200,
    epochs: int = 25,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Train the Deep Knowledge Tracing model for a subject on real quiz
    logs augmented with IRT-simulated students; persists the model."""
    _ = user
    from app.services.dkt_service import train_subject_dkt

    try:
        return await train_subject_dkt(
            db,
            subject_id,
            synthetic_students=max(0, min(int(synthetic_students), 1000)),
            epochs=max(5, min(int(epochs), 100)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    session.theta_estimate = _safe_numeric(
        score_result.get("theta"),
        default=0.0,
        min_value=-999.0,
        max_value=999.0,
        ndigits=2,
    )

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
        progress.theta_estimate = _safe_numeric(
            tscore.get("theta"),
            default=0.0,
            min_value=-999.0,
            max_value=999.0,
            ndigits=2,
        )
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
    scoring_data: list[dict] = []
    answered_count = 0

    for r in responses:
        q = r.question
        tname = q.topic.name if q.topic else "Unknown"

        if tname not in topic_scores:
            topic_scores[tname] = {"correct": 0, "total": 0, "mastery": "beginner"}
        topic_scores[tname]["total"] += 1
        if r.is_correct:
            topic_scores[tname]["correct"] += 1
        if r.user_answer is not None:
            answered_count += 1

        scoring_data.append({
            "a": float(q.discrimination_a),
            "b": float(q.difficulty_b),
            "c": float(q.guessing_c),
            "is_correct": bool(r.is_correct),
            "question_type": q.question_type,
            "topic_id": q.topic_id,
            "topic_name": tname,
            "major_topic_name": q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            "is_sql": _is_sql_context(
                q.topic.name if q.topic else "",
                q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
            ),
            "guessing_flag": bool(r.guessing_flag),
        })

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

    # Calculate per-topic mastery using unified ability estimation
    for tname in topic_scores.keys():
        topic_responses = [sd for sd in scoring_data if sd["topic_name"] == tname]
        if topic_responses:
            topic_ability = estimate_ability_3pl(topic_responses)
            topic_theta = topic_ability["theta_map"]
            topic_scores[tname]["theta"] = round(topic_theta, 2)
            topic_scores[tname]["mastery"] = classify_mastery(topic_theta)

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
        chain_id=session.chain_id,
        exam_index=session.exam_index,
    )

    accuracy = (
        float(session.correct_answers or 0) / float(session.total_questions or 1)
        if (session.total_questions or 0) > 0
        else 0.0
    )
    theta_for_eval = float(session.theta_estimate or 0.0)
    # Calculate uncertainty using unified Bayesian method
    if scoring_data:
        ability_result = estimate_ability_3pl(scoring_data)
        sem_for_eval = _safe_numeric(
            ability_result["posterior_sd"],
            default=999.0,
            min_value=0.0,
            max_value=999.0,
            ndigits=3,
        )
    else:
        sem_for_eval = _safe_numeric(
            999.0,
            default=999.0,
            min_value=0.0,
            max_value=999.0,
            ndigits=3,
        )
    bloom_classification = _classify_bloom(theta_for_eval, scoring_data)

    return QuizResultOut(
        session=session_out,
        results=results,
        topic_scores=topic_scores,
        accuracy=round(float(accuracy), 4),
        sem=sem_for_eval,
        answered_count=answered_count,
        bloom_classification=bloom_classification,
    )


@router.get("/{session_id}/explanation")
async def get_session_explanation(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Explainable AI: decompose the ability estimate — per-question theta
    impact, Fisher information share, difficulty/Bloom breakdown, and a
    rule-based Vietnamese narrative."""
    from app.engine.irt import information_3pl
    from app.engine.rules import classify_difficulty_level
    from app.services.adaptive_shared import (
        build_scoring_data,
        normalize_question_type,
        theta_history_from_scoring_data,
    )

    session = await db.get(QuizSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Quiz session not found")

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
    responses = result.scalars().all()
    if not responses:
        raise HTTPException(status_code=400, detail="Session has no responses")

    scoring_data = build_scoring_data(responses)
    theta_history = theta_history_from_scoring_data(scoring_data)
    final_theta = theta_history[-1]

    # Rolling SEM (posterior SD) after each answered question
    sem_history: list[float] = []
    for i in range(1, len(scoring_data) + 1):
        sem_history.append(
            round(float(estimate_ability_3pl(scoring_data[:i])["posterior_sd"]), 3)
        )
    final_sem = sem_history[-1] if sem_history else 999.0

    total_info = sum(
        information_3pl(final_theta, r["a"], r["b"], r["c"]) for r in scoring_data
    )

    questions_detail = []
    for i, (resp, row) in enumerate(zip(responses, scoring_data)):
        info = information_3pl(final_theta, row["a"], row["b"], row["c"])
        questions_detail.append(
            {
                "question_id": resp.question_id,
                "external_id": resp.question.external_id,
                "order": i + 1,
                "topic_name": row["topic_name"],
                "question_type": row["question_type"],
                "difficulty_b": row["b"],
                "difficulty_level": classify_difficulty_level(row["b"]),
                "is_correct": row["is_correct"],
                "guessing_flag": row["guessing_flag"],
                "delta_theta": round(theta_history[i + 1] - theta_history[i], 3),
                "fisher_information": round(float(info), 4),
                "information_share": round(float(info) / total_info, 4) if total_info > 0 else 0.0,
            }
        )

    # Bloom-level skill breakdown
    bloom_labels = {"nhan_biet": "Nhận biết", "thong_hieu": "Thông hiểu", "van_dung": "Vận dụng"}
    bloom_stats: dict[str, dict] = {}
    for row in scoring_data:
        key = normalize_question_type(row.get("question_type"))
        label = bloom_labels.get(key, row.get("question_type") or "Khác")
        agg = bloom_stats.setdefault(label, {"total": 0, "correct": 0})
        agg["total"] += 1
        if row["is_correct"]:
            agg["correct"] += 1
    for label, agg in bloom_stats.items():
        agg["accuracy"] = round(agg["correct"] / agg["total"], 4) if agg["total"] else 0.0

    # Skill layer: comprehension skills are measured by Nhận biết/Thông hiểu
    # questions of the topic, application skills by Vận dụng questions.
    from app.models.knowledge import Skill

    session_topic_ids = {row["topic_id"] for row in scoring_data if row.get("topic_id")}
    skill_rows = await db.execute(
        select(Skill).where(Skill.topic_id.in_(session_topic_ids) if session_topic_ids else False)
    )
    skill_stats: list[dict] = []
    for skill in skill_rows.scalars().all():
        if skill.kind == "application":
            matched = [
                r for r in scoring_data
                if r.get("topic_id") == skill.topic_id
                and normalize_question_type(r.get("question_type")) == "van_dung"
            ]
        else:
            matched = [
                r for r in scoring_data
                if r.get("topic_id") == skill.topic_id
                and normalize_question_type(r.get("question_type")) in ("nhan_biet", "thong_hieu")
            ]
        if not matched:
            continue
        s_correct = sum(1 for r in matched if r["is_correct"])
        skill_stats.append(
            {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "kind": skill.kind,
                "topic_id": skill.topic_id,
                "total": len(matched),
                "correct": s_correct,
                "accuracy": round(s_correct / len(matched), 4),
            }
        )
    skill_stats.sort(key=lambda s: -s["accuracy"])

    # Difficulty-level breakdown
    difficulty_stats: dict[str, dict] = {}
    for row in scoring_data:
        level = classify_difficulty_level(row["b"])
        agg = difficulty_stats.setdefault(level, {"total": 0, "correct": 0})
        agg["total"] += 1
        if row["is_correct"]:
            agg["correct"] += 1
    for level, agg in difficulty_stats.items():
        agg["accuracy"] = round(agg["correct"] / agg["total"], 4) if agg["total"] else 0.0

    # ---------- Rule-based Vietnamese narrative ----------
    correct_count = sum(1 for r in scoring_data if r["is_correct"])
    total = len(scoring_data)
    mastery = classify_mastery(final_theta)
    mastery_vi = {
        "master": "Xuất sắc", "proficient": "Giỏi", "developing": "Khá",
        "beginner": "Trung bình", "novice": "Cần cải thiện",
    }.get(mastery, mastery)

    narrative: list[str] = []
    narrative.append(
        f"Bạn trả lời đúng {correct_count}/{total} câu. Năng lực ước lượng θ = {final_theta:.2f} "
        f"(mức {mastery_vi}), với độ bất định SEM = {final_sem:.3f} — "
        + ("đủ tin cậy để kết luận (SEM < 0.3)." if final_sem < 0.3
           else "chưa đạt ngưỡng tin cậy SEM < 0.3, nên làm thêm để ước lượng chính xác hơn.")
    )

    biggest_up = max(questions_detail, key=lambda q: q["delta_theta"])
    biggest_down = min(questions_detail, key=lambda q: q["delta_theta"])
    if biggest_up["delta_theta"] > 0:
        narrative.append(
            f"Câu kéo năng lực lên mạnh nhất là câu {biggest_up['order']} "
            f"({biggest_up['external_id']}, {biggest_up['difficulty_level'].lower()}, "
            f"b = {biggest_up['difficulty_b']:.2f}): trả lời đúng câu này làm θ tăng "
            f"{biggest_up['delta_theta']:+.3f}."
        )
    if biggest_down["delta_theta"] < 0:
        narrative.append(
            f"Câu kéo năng lực xuống nhiều nhất là câu {biggest_down['order']} "
            f"({biggest_down['external_id']}, {biggest_down['difficulty_level'].lower()}, "
            f"b = {biggest_down['difficulty_b']:.2f}): θ giảm {biggest_down['delta_theta']:+.3f}."
        )

    most_informative = max(questions_detail, key=lambda q: q["fisher_information"])
    narrative.append(
        f"Câu đo năng lực chính xác nhất (Fisher Information cao nhất tại θ của bạn) là câu "
        f"{most_informative['order']} ({most_informative['external_id']}), đóng góp "
        f"{most_informative['information_share'] * 100:.0f}% tổng lượng thông tin của bài."
    )

    strong_bloom = max(bloom_stats.items(), key=lambda kv: kv[1]["accuracy"], default=None)
    weak_bloom = min(bloom_stats.items(), key=lambda kv: kv[1]["accuracy"], default=None)
    if strong_bloom and weak_bloom and strong_bloom[0] != weak_bloom[0]:
        narrative.append(
            f"Về kỹ năng đo được theo thang Bloom: bạn mạnh nhất ở mức {strong_bloom[0]} "
            f"({strong_bloom[1]['correct']}/{strong_bloom[1]['total']} đúng) và yếu nhất ở mức "
            f"{weak_bloom[0]} ({weak_bloom[1]['correct']}/{weak_bloom[1]['total']} đúng)."
        )

    if skill_stats:
        best_skill = skill_stats[0]
        worst_skill = skill_stats[-1]
        if best_skill["skill_id"] != worst_skill["skill_id"]:
            narrative.append(
                f"Xét theo tầng kỹ năng của ontology: bạn thể hiện tốt nhất ở kỹ năng "
                f"\"{best_skill['skill_name']}\" ({best_skill['correct']}/{best_skill['total']} đúng) "
                f"và cần rèn thêm kỹ năng \"{worst_skill['skill_name']}\" "
                f"({worst_skill['correct']}/{worst_skill['total']} đúng)."
            )

    guessed = [q for q in questions_detail if q["guessing_flag"]]
    if guessed:
        narrative.append(
            f"Hệ thống phát hiện {len(guessed)} câu nghi ngờ đoán mò (đúng quá nhanh trên câu dễ đoán) "
            f"— mức tăng θ từ các câu này đã được giảm trọng số (luật R7)."
        )

    topic_acc: dict[str, dict] = {}
    for row in scoring_data:
        agg = topic_acc.setdefault(row["topic_name"], {"total": 0, "correct": 0})
        agg["total"] += 1
        if row["is_correct"]:
            agg["correct"] += 1
    weak_topics = [
        name for name, agg in topic_acc.items()
        if agg["total"] >= 2 and agg["correct"] / agg["total"] < 0.5
    ]
    if weak_topics:
        narrative.append(
            "Chủ đề cần ôn lại: " + ", ".join(weak_topics)
            + " (tỷ lệ đúng dưới 50%). Xem gợi ý kiến thức tiên quyết ở phần khuyến nghị."
        )

    return {
        "session_id": session_id,
        "theta": round(float(final_theta), 3),
        "sem": round(float(final_sem), 3),
        "mastery": mastery,
        "theta_history": theta_history,
        "sem_history": sem_history,
        "questions": questions_detail,
        "bloom_stats": bloom_stats,
        "difficulty_stats": difficulty_stats,
        "skill_stats": skill_stats,
        "narrative": narrative,
    }


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
