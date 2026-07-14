"""Shared helpers for adaptive testing (exam-batch CAT).

Moved out of api/quiz.py so both the quiz router and the exam-generation
engine can reuse rule helpers, scoring-data builders and LLM persistence
without importing the whole router module.
"""
from datetime import datetime, timezone
import math

from app.config import get_settings

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import QuizResponse, QuizSession, UserTopicProgress
from app.models.question import Question
from app.models.knowledge import Topic, MajorTopic, TopicPrerequisite
from app.models.cat_knowledge import KnowledgeGraph
from app.schemas.question import LearningRecommendation, QuestionOut
from app.engine.irt import estimate_ability_3pl
from app.engine.rules import topic_error_rates, classify_difficulty_level
from app.engine.llm_generation import generate_validated_question_for_cat


def safe_numeric(
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

    parsed = min(max(parsed, min_value), max_value)
    return round(parsed, ndigits)


def apply_forgetting(theta: float, last_practiced_at) -> tuple[float, int]:
    """Ebbinghaus-style decay: effective theta drops the longer a topic sits
    unreviewed. Returns (theta_effective, days_idle)."""
    settings = get_settings()
    lam = float(settings.FORGETTING_LAMBDA)
    if last_practiced_at is None or lam <= 0:
        return float(theta), 0

    now = datetime.now(timezone.utc)
    last = last_practiced_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    theta_eff = float(theta) - lam * math.log1p(days)
    return round(theta_eff, 3), int(days)


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def question_signature_from_payload(payload: dict) -> str:
    return "|".join(
        [
            normalize_text(str(payload.get("stem", ""))),
            normalize_text(str(payload.get("option_a", ""))),
            normalize_text(str(payload.get("option_b", ""))),
            normalize_text(str(payload.get("option_c", ""))),
            normalize_text(str(payload.get("option_d", ""))),
            normalize_text(str(payload.get("correct_answer", ""))),
        ]
    )


def question_signature_from_model(q: Question) -> str:
    return "|".join(
        [
            normalize_text(q.stem),
            normalize_text(q.option_a),
            normalize_text(q.option_b),
            normalize_text(q.option_c),
            normalize_text(q.option_d),
            normalize_text(q.correct_answer),
        ]
    )


def normalize_question_type(qtype: str | None) -> str:
    text = (qtype or "").strip().lower()
    if "nhận" in text or "nhan" in text:
        return "nhan_biet"
    if "thông" in text or "thong" in text:
        return "thong_hieu"
    if "vận" in text or "van" in text:
        return "van_dung"
    return text


def is_sql_context(topic_name: str | None, major_topic_name: str | None) -> bool:
    text = f"{topic_name or ''} {major_topic_name or ''}".lower()
    sql_keywords = ["sql", "database", "cơ sở dữ liệu", "co so du lieu", "join", "query"]
    return any(k in text for k in sql_keywords)


def pick_min_b_gap(candidates: list[dict], target_b: float) -> dict | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda q: (abs(float(q["difficulty_b"]) - float(target_b)), -float(q.get("discrimination_a", 0.0))),
    )


def count_consecutive_correct_on_topic(scoring_data: list[dict], topic_id: int) -> int:
    """Count how many of the most recent answers on *topic_id* were correct in a row.

    Iterates from newest to oldest; stops as soon as a wrong answer (on that topic) is found.
    Answers on other topics are ignored so topic-specific streaks are tracked independently.
    """
    count = 0
    for item in reversed(scoring_data):
        if item.get("topic_id") != topic_id:
            continue
        if item.get("is_correct"):
            count += 1
        else:
            break
    return count


def count_consecutive_fail_on_topic(scoring_data: list[dict], topic_id: int) -> int:
    """Count how many of the most recent answers on *topic_id* were wrong in a row.

    Iterates from newest to oldest; stops as soon as a correct answer (on that topic) is found.
    """
    count = 0
    for item in reversed(scoring_data):
        if item.get("topic_id") != topic_id:
            continue
        if not item.get("is_correct"):
            count += 1
        else:
            break
    return count


def build_scoring_data(responses: list[QuizResponse]) -> list[dict]:
    """Build the scoring_data row list used by IRT estimation and the rule engine.

    Each response must have question -> topic -> major_topic eagerly loaded.
    """
    scoring_data: list[dict] = []
    for r in responses:
        q = r.question
        topic_name = q.topic.name if q.topic else str(q.topic_id)
        major_topic_name = q.topic.major_topic.name if q.topic and q.topic.major_topic else ""
        scoring_data.append(
            {
                "a": float(q.discrimination_a),
                "b": float(q.difficulty_b),
                "c": float(q.guessing_c),
                "is_correct": bool(r.is_correct),
                "topic_id": q.topic_id,
                "topic_name": topic_name,
                "major_topic_name": major_topic_name,
                "question_type": q.question_type,
                "is_sql": is_sql_context(topic_name, major_topic_name),
                "guessing_flag": bool(r.guessing_flag),
                "difficulty_level": classify_difficulty_level(float(q.difficulty_b)),
            }
        )
    return scoring_data


async def pick_r12_computation_target_topic(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    candidate_topic_ids: set[int],
    session_scoring_data: list[dict] | None = None,
) -> tuple[int | None, list[int]]:
    """Pick Topic_C where prerequisites are already mastered (A, B -> C style).

    R12 intent: when learner has demonstrated mastery in prerequisite topics,
    infer higher readiness for dependent topic and prioritize it.

    Mastery evidence is merged from:
    1) persisted progress (UserTopicProgress), and
    2) current session signals in scoring_data.
    """
    if not candidate_topic_ids:
        return None, []

    edges_result = await db.execute(
        select(KnowledgeGraph.source_id, KnowledgeGraph.target_id)
        .where(KnowledgeGraph.subject_id == subject_id)
        .where(KnowledgeGraph.source_type == "topic")
        .where(KnowledgeGraph.target_type == "topic")
        .where(KnowledgeGraph.relation_type == "prerequisite")
    )
    edges = edges_result.all()
    if not edges:
        return None, []

    prereq_map: dict[int, set[int]] = {}
    for source_id, target_id in edges:
        prereq_map.setdefault(int(source_id), set()).add(int(target_id))

    # Strict R12 gating: require at least 2 mastered prerequisites to mimic A,B -> C.
    prerequisites_by_topic = {
        topic_id: sorted(list(prereqs))
        for topic_id, prereqs in prereq_map.items()
        if topic_id in candidate_topic_ids and len(prereqs) >= 2
    }
    if not prerequisites_by_topic:
        return None, []

    all_prereq_ids = {
        prereq_id for prereq_ids in prerequisites_by_topic.values() for prereq_id in prereq_ids
    }
    if not all_prereq_ids:
        return None, []

    mastery_rank = {
        "novice": 0,
        "beginner": 1,
        "developing": 2,
        "proficient": 3,
        "master": 4,
    }

    mastered_prereq_ids: set[int] = set()

    progress_result = await db.execute(
        select(UserTopicProgress)
        .where(UserTopicProgress.user_id == user_id)
        .where(UserTopicProgress.topic_id.in_(all_prereq_ids))
    )
    progresses = progress_result.scalars().all()
    for p in progresses:
        level = (p.mastery_level or "").strip().lower()
        theta_val = float(p.theta_estimate or 0.0)
        if mastery_rank.get(level, 0) >= 3 or theta_val >= 0.7:
            mastered_prereq_ids.add(int(p.topic_id))

    # Add in-session mastery evidence so R12 can react within the current test run.
    session_scoring_data = session_scoring_data or []
    per_topic: dict[int, dict[str, float]] = {}
    for row in session_scoring_data:
        topic_id_raw = row.get("topic_id")
        if topic_id_raw is None:
            continue
        topic_id = int(topic_id_raw)
        if topic_id not in all_prereq_ids:
            continue
        agg = per_topic.setdefault(topic_id, {"total": 0.0, "correct": 0.0})
        agg["total"] += 1.0
        if bool(row.get("is_correct")):
            agg["correct"] += 1.0

    for topic_id, agg in per_topic.items():
        total = float(agg["total"])
        correct = float(agg["correct"])
        accuracy = (correct / total) if total > 0 else 0.0
        # Session-based mastery heuristic: enough evidence and stable accuracy.
        if total >= 2.0 and accuracy >= 0.75:
            mastered_prereq_ids.add(int(topic_id))

    best_topic_id = None
    best_prereqs: list[int] = []
    for topic_id, prereq_ids in prerequisites_by_topic.items():
        if all(pr in mastered_prereq_ids for pr in prereq_ids):
            if best_topic_id is None or len(prereq_ids) > len(best_prereqs):
                best_topic_id = topic_id
                best_prereqs = prereq_ids

    return best_topic_id, best_prereqs


def classify_bloom(theta: float, scoring_data: list[dict]) -> str | None:
    app_rows = [r for r in scoring_data if normalize_question_type(r.get("question_type")) == "van_dung"]
    app_acc = sum(1 for r in app_rows if r.get("is_correct")) / len(app_rows) if app_rows else 0.0
    if float(theta) > 1.5 and app_acc > 0.8:
        return "Xuất sắc - Có khả năng giải quyết vấn đề phức tạp"
    return None


def append_rule(
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


def question_to_out(q: Question) -> QuestionOut:
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


def theta_history_from_scoring_data(
    scoring_data: list[dict],
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
) -> list[float]:
    """Build theta timeline step-by-step, including R7 damping behavior.

    prior_mean/prior_sd let a warm-started chain (DKT/UserAbility prior)
    keep the same informative prior across the whole timeline.
    """
    history = [round(float(prior_mean), 3)]
    rolling_data: list[dict] = []
    current_theta = float(prior_mean)

    for row in scoring_data:
        rolling_data.append(
            {
                "a": float(row["a"]),
                "b": float(row["b"]),
                "c": float(row["c"]),
                "is_correct": bool(row["is_correct"]),
            }
        )
        ability_result = estimate_ability_3pl(
            rolling_data, prior_mean=prior_mean, prior_sd=prior_sd
        )
        raw_theta = ability_result["theta_map"]
        if bool(row.get("guessing_flag")):
            # Keep timeline consistent with runtime theta damping under R7.
            current_theta = current_theta + 0.3 * (raw_theta - current_theta)
        else:
            current_theta = raw_theta

        current_theta = safe_numeric(
            current_theta,
            default=0.0,
            min_value=-999.0,
            max_value=999.0,
        )
        history.append(round(float(current_theta), 3))

    return history


def theta_history_from_responses(responses: list[QuizResponse]) -> list[float]:
    scoring_data = []
    for r in responses:
        q = r.question
        scoring_data.append(
            {
                "a": float(q.discrimination_a),
                "b": float(q.difficulty_b),
                "c": float(q.guessing_c),
                "is_correct": bool(r.is_correct),
                "guessing_flag": bool(r.guessing_flag),
            }
        )
    return theta_history_from_scoring_data(scoring_data)


async def recent_answered_question_ids(
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


async def build_recommendations(db: AsyncSession, responses: list[QuizResponse]) -> list[LearningRecommendation]:
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


def target_level_from_theta(theta: float) -> str:
    if theta < -0.5:
        return "Nhận biết"
    if theta < 0.7:
        return "Thông hiểu"
    return "Vận dụng"


async def build_topic_context(db: AsyncSession, topic_id: int) -> str:
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


async def pick_start_topic_id_for_cat(
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


async def generate_and_persist_cat_question(
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

    target_level = target_level_from_theta(theta)
    target_b = max(-2.5, min(2.5, float(theta)))
    target_a = 1.5 if target_level == "Vận dụng" else (1.2 if target_level == "Thông hiểu" else 1.0)
    target_c = 0.2 if target_level != "Vận dụng" else 0.15

    context = await build_topic_context(db, topic_id)
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
        candidate_signature = question_signature_from_payload(candidate_generated)
        if candidate_signature in blocked_signatures:
            continue

        stem_norm = normalize_text(candidate_generated["stem"])
        existing_same_stem = await db.execute(
            select(Question).where(
                Question.topic_id == topic_id,
                func.lower(func.trim(Question.stem)) == stem_norm,
            ).limit(1)
        )
        existing_question = existing_same_stem.scalars().first()
        if existing_question:
            blocked_signatures.add(question_signature_from_model(existing_question))
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
