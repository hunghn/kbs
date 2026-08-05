"""Question management API: CRUD for question bank."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_user
from app.database import get_db
from app.models.knowledge import Topic, MajorTopic
from app.models.question import Question
from app.models.user import User, QuizResponse
from app.schemas.question import (
    QuestionCreate,
    QuestionFormatStatsOut,
    QuestionManageListOut,
    QuestionManageOut,
    QuestionUpdate,
)
from app.services.question_format import (
    GUESSING_C_BOUNDS,
    SUPPORTED_FORMATS,
    normalize_format,
    normalize_format_fields,
    parse_matching_pairs,
)

router = APIRouter(prefix="/api/questions", tags=["questions"])

# Columns owned by the format normalizer; everything else is copied verbatim
_FORMAT_OWNED_FIELDS = (
    "question_format",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "correct_answer",
    "answer_text",
    "matching_pairs",
    "guessing_c",
)


def _to_manage_out(q: Question) -> QuestionManageOut:
    fmt = normalize_format(q.question_format)
    return QuestionManageOut(
        id=q.id,
        external_id=q.external_id,
        topic_id=q.topic_id,
        topic_name=q.topic.name if q.topic else "",
        major_topic_name=q.topic.major_topic.name if q.topic and q.topic.major_topic else "",
        stem=q.stem,
        question_format=fmt,
        option_a=q.option_a,
        option_b=q.option_b,
        option_c=q.option_c,
        option_d=q.option_d,
        correct_answer=q.correct_answer,
        answer_text=q.answer_text if fmt == "short_answer" else None,
        matching_pairs=parse_matching_pairs(q.matching_pairs) if fmt == "matching" else [],
        difficulty_b=float(q.difficulty_b),
        discrimination_a=float(q.discrimination_a),
        guessing_c=float(q.guessing_c),
        question_type=q.question_type,
        time_limit_seconds=q.time_limit_seconds,
        time_display=q.time_display,
        is_archived=bool(q.is_archived),
    )


def _apply_filters(query, *, subject_id, topic_id, search, include_archived, question_format):
    """Shared WHERE clauses for list / count / stats so they never diverge."""
    if not include_archived:
        query = query.where(Question.is_archived.is_(False))

    if topic_id is not None:
        query = query.where(Question.topic_id == topic_id)
    elif subject_id is not None:
        query = query.join(Topic).join(MajorTopic).where(MajorTopic.subject_id == subject_id)

    if question_format:
        query = query.where(Question.question_format == question_format)

    if search:
        query = query.where(Question.stem.ilike(f"%{search}%"))

    return query


@router.get("", response_model=QuestionManageListOut)
async def list_questions(
    subject_id: int | None = None,
    topic_id: int | None = None,
    search: str | None = None,
    question_format: str | None = None,
    include_archived: bool = True,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    if question_format and question_format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail="Dạng câu hỏi không hỗ trợ")

    filters = dict(
        subject_id=subject_id,
        topic_id=topic_id,
        search=search,
        include_archived=include_archived,
        question_format=question_format,
    )

    base_query = _apply_filters(select(Question.id), **filters)
    total_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = int(total_result.scalar_one() or 0)

    query = _apply_filters(
        select(Question).options(selectinload(Question.topic).selectinload(Topic.major_topic)),
        **filters,
    )
    query = query.order_by(Question.id.desc()).offset(skip).limit(min(limit, 200))

    result = await db.execute(query)
    questions = result.scalars().unique().all()
    return QuestionManageListOut(
        items=[_to_manage_out(q) for q in questions],
        total=total,
        skip=max(0, int(skip)),
        limit=min(max(1, int(limit)), 200),
    )


@router.get("/format-stats", response_model=QuestionFormatStatsOut)
async def question_format_stats(
    subject_id: int | None = None,
    topic_id: int | None = None,
    search: str | None = None,
    include_archived: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-format counts for the current filter (drives the dashboard tiles)."""
    _ = user
    filters = dict(
        subject_id=subject_id,
        topic_id=topic_id,
        search=search,
        include_archived=include_archived,
        question_format=None,
    )

    rows = await db.execute(
        _apply_filters(
            select(Question.question_format, Question.is_archived, func.count(Question.id)),
            **filters,
        ).group_by(Question.question_format, Question.is_archived)
    )

    stats = QuestionFormatStatsOut()
    for fmt_value, is_archived, count in rows.all():
        count = int(count or 0)
        stats.total += count
        if is_archived:
            stats.archived += count
        setattr(stats, normalize_format(fmt_value), getattr(stats, normalize_format(fmt_value)) + count)
    return stats


@router.get("/{question_id}", response_model=QuestionManageOut)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    result = await db.execute(
        select(Question)
        .where(Question.id == question_id)
        .options(selectinload(Question.topic).selectinload(Topic.major_topic))
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    return _to_manage_out(q)


@router.post("", response_model=QuestionManageOut)
async def create_question(
    payload: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    existing = await db.execute(select(Question).where(Question.external_id == payload.external_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="external_id already exists")

    topic = await db.get(Topic, payload.topic_id)
    if not topic:
        raise HTTPException(status_code=400, detail="topic_id is invalid")

    data = payload.model_dump()
    try:
        fields = normalize_format_fields(data.get("question_format"), data, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    display = payload.time_display or f"{payload.time_limit_seconds // 60:02d}:{payload.time_limit_seconds % 60:02d}"

    question = Question(
        external_id=payload.external_id,
        topic_id=payload.topic_id,
        stem=payload.stem,
        difficulty_b=payload.difficulty_b,
        discrimination_a=payload.discrimination_a,
        question_type=payload.question_type,
        time_limit_seconds=payload.time_limit_seconds,
        time_display=display,
        is_archived=False,
        **fields,
    )
    db.add(question)
    await db.commit()

    return await get_question(question.id, db, user)


@router.put("/{question_id}", response_model=QuestionManageOut)
async def update_question(
    question_id: int,
    payload: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    q = await db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    data = payload.model_dump(exclude_unset=True)
    if "external_id" in data and data["external_id"] != q.external_id:
        dup = await db.execute(select(Question).where(Question.external_id == data["external_id"]))
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="external_id already exists")

    if "topic_id" in data:
        topic = await db.get(Topic, data["topic_id"])
        if not topic:
            raise HTTPException(status_code=400, detail="topic_id is invalid")

    current_fmt = normalize_format(q.question_format)
    new_fmt = normalize_format(data["question_format"]) if "question_format" in data else current_fmt
    if new_fmt != current_fmt:
        answered = await db.execute(
            select(QuizResponse.id).where(QuizResponse.question_id == question_id).limit(1)
        )
        if answered.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Câu hỏi đã có lịch sử làm bài nên không thể đổi dạng. "
                    "Hãy archive câu này và tạo câu mới ở dạng mong muốn."
                ),
            )

    # Merge the submitted format fields over the stored ones, then re-normalize
    # as a whole so a partial update can never leave the row half-converted.
    merged = {
        "option_a": q.option_a,
        "option_b": q.option_b,
        "option_c": q.option_c,
        "option_d": q.option_d,
        "correct_answer": q.correct_answer,
        "answer_text": q.answer_text,
        "matching_pairs": parse_matching_pairs(q.matching_pairs),
        "guessing_c": float(q.guessing_c),
    }
    # A format switch discards the previous format's key material
    if new_fmt != current_fmt:
        merged.update({"answer_text": None, "matching_pairs": [], "guessing_c": None})
    merged.update({k: v for k, v in data.items() if k in _FORMAT_OWNED_FIELDS})

    if "guessing_c" not in data and merged.get("guessing_c") is not None:
        # Keep an already-calibrated c, but repair legacy values that fall
        # outside the format bounds instead of blocking an unrelated edit.
        low, high = GUESSING_C_BOUNDS[new_fmt]
        merged["guessing_c"] = min(max(float(merged["guessing_c"]), low), high)

    try:
        fields = normalize_format_fields(new_fmt, merged, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    for k, v in data.items():
        if k not in _FORMAT_OWNED_FIELDS:
            setattr(q, k, v)
    for k, v in fields.items():
        setattr(q, k, v)

    if payload.time_limit_seconds is not None and payload.time_display is None:
        q.time_display = f"{q.time_limit_seconds // 60:02d}:{q.time_limit_seconds % 60:02d}"

    await db.commit()
    return await get_question(question_id, db, user)


@router.delete("/{question_id}")
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    q = await db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    used_result = await db.execute(
        select(QuizResponse.id)
        .where(QuizResponse.question_id == question_id)
        .limit(1)
    )
    if used_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Question has quiz history and cannot be deleted. Use archive instead.",
        )

    await db.delete(q)
    await db.commit()
    return {"message": "Question deleted", "id": question_id}


@router.post("/{question_id}/archive", response_model=QuestionManageOut)
async def archive_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    q = await db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    q.is_archived = True
    await db.commit()
    return await get_question(question_id, db, user)


@router.post("/{question_id}/unarchive", response_model=QuestionManageOut)
async def unarchive_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    q = await db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    q.is_archived = False
    await db.commit()
    return await get_question(question_id, db, user)
