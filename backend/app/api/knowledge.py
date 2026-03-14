"""Knowledge API: Subjects, Major Topics, Topics (Ontology tree)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.knowledge import Subject, MajorTopic, Topic
from app.models.question import Question
from app.schemas.knowledge import SubjectOut, SubjectSummary, KnowledgeTreeOut, TopicOut

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/subjects", response_model=list[SubjectSummary])
async def list_subjects(db: AsyncSession = Depends(get_db)):
    """List all subjects with summary stats."""
    result = await db.execute(
        select(Subject).options(
            selectinload(Subject.major_topics).selectinload(MajorTopic.topics)
        )
    )
    subjects = result.scalars().unique().all()

    summaries = []
    for s in subjects:
        total_topics = sum(len(mt.topics) for mt in s.major_topics)
        # Count questions
        q_result = await db.execute(
            select(func.count(Question.id)).join(Topic).join(MajorTopic).where(
                MajorTopic.subject_id == s.id,
                Question.is_archived.is_(False),
            )
        )
        total_questions = q_result.scalar() or 0
        summaries.append(SubjectSummary(
            id=s.id,
            name=s.name,
            description=s.description,
            total_questions=total_questions,
            total_topics=total_topics,
        ))
    return summaries


@router.get("/subjects/{subject_id}/tree", response_model=KnowledgeTreeOut)
async def get_knowledge_tree(subject_id: int, db: AsyncSession = Depends(get_db)):
    """Get full ontology tree for a subject."""
    result = await db.execute(
        select(Subject)
        .where(Subject.id == subject_id)
        .options(
            selectinload(Subject.major_topics)
            .selectinload(MajorTopic.topics)
            .selectinload(Topic.questions)
        )
    )
    subject = result.scalar_one_or_none()
    if not subject:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Subject not found")

    topic_ids = [t.id for mt in subject.major_topics for t in mt.topics]
    count_map: dict[int, int] = {}
    if topic_ids:
        count_result = await db.execute(
            select(Question.topic_id, func.count(Question.id))
            .where(Question.topic_id.in_(topic_ids), Question.is_archived.is_(False))
            .group_by(Question.topic_id)
        )
        count_map = {tid: cnt for tid, cnt in count_result.all()}

    # Build response with question counts
    subject_out = SubjectOut(
        id=subject.id,
        name=subject.name,
        description=subject.description,
        major_topics=[
            {
                "id": mt.id,
                "subject_id": mt.subject_id,
                "code": mt.code,
                "name": mt.name,
                "order_index": mt.order_index,
                "topics": [
                    TopicOut(
                        id=t.id,
                        major_topic_id=t.major_topic_id,
                        code=t.code,
                        name=t.name,
                        order_index=t.order_index,
                        question_count=int(count_map.get(t.id, 0)),
                    )
                    for t in mt.topics
                ],
            }
            for mt in subject.major_topics
        ],
    )
    return KnowledgeTreeOut(subject=subject_out)


@router.get("/topics", response_model=list[TopicOut])
async def list_topics(
    subject_id: int = None,
    db: AsyncSession = Depends(get_db),
):
    """List topics, optionally filtered by subject."""
    query = select(Topic).options(selectinload(Topic.questions))
    if subject_id:
        query = query.join(MajorTopic).where(MajorTopic.subject_id == subject_id)

    result = await db.execute(query)
    topics = result.scalars().unique().all()

    topic_ids = [t.id for t in topics]
    count_map: dict[int, int] = {}
    if topic_ids:
        count_result = await db.execute(
            select(Question.topic_id, func.count(Question.id))
            .where(Question.topic_id.in_(topic_ids), Question.is_archived.is_(False))
            .group_by(Question.topic_id)
        )
        count_map = {tid: cnt for tid, cnt in count_result.all()}

    return [
        TopicOut(
            id=t.id,
            major_topic_id=t.major_topic_id,
            code=t.code,
            name=t.name,
            order_index=t.order_index,
            question_count=int(count_map.get(t.id, 0)),
        )
        for t in topics
    ]
