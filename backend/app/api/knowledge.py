"""Knowledge API: Subjects, Major Topics, Topics (Ontology tree)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.api.auth import get_current_user
from app.models.knowledge import Subject, MajorTopic, Topic, TopicPrerequisite, Skill
from app.models.question import Question
from app.models.user import User, UserTopicProgress
from app.models.cat_knowledge import KnowledgeGraph
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


@router.get("/subjects/{subject_id}/ability-graph")
async def get_ability_graph(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Personal competency knowledge graph: ontology topics colored by the
    current user's mastery, with prerequisite/inference edges."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    topics_result = await db.execute(
        select(Topic, MajorTopic)
        .join(MajorTopic, MajorTopic.id == Topic.major_topic_id)
        .where(MajorTopic.subject_id == subject_id)
        .order_by(MajorTopic.order_index.asc(), Topic.order_index.asc(), Topic.id.asc())
    )
    rows = topics_result.all()
    topic_ids = [t.id for t, _mt in rows]

    progress_result = await db.execute(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user.id,
            UserTopicProgress.topic_id.in_(topic_ids) if topic_ids else False,
        )
    )
    progress = {p.topic_id: p for p in progress_result.scalars().all()}

    count_result = await db.execute(
        select(Question.topic_id, func.count(Question.id))
        .where(Question.topic_id.in_(topic_ids) if topic_ids else False)
        .where(Question.is_archived.is_(False))
        .group_by(Question.topic_id)
    )
    count_map = {tid: cnt for tid, cnt in count_result.all()}

    skills_result = await db.execute(
        select(Skill).where(Skill.topic_id.in_(topic_ids) if topic_ids else False)
    )
    skills_map: dict[int, list[dict]] = {}
    for s in skills_result.scalars().all():
        skills_map.setdefault(s.topic_id, []).append(
            {"id": s.id, "name": s.name, "kind": s.kind}
        )

    from app.engine.irt import classify_mastery
    from app.services.adaptive_shared import apply_forgetting

    nodes = []
    for t, mt in rows:
        p = progress.get(t.id)
        theta = float(p.theta_estimate) if p and p.theta_estimate is not None else None
        theta_eff, days_idle, mastery_eff = None, 0, None
        if p and theta is not None and (p.questions_attempted or 0) > 0:
            theta_eff, days_idle = apply_forgetting(theta, p.updated_at)
            mastery_eff = classify_mastery(theta_eff)
        nodes.append(
            {
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "major_topic_id": mt.id,
                "major_topic_name": mt.name,
                "major_topic_order": mt.order_index or 0,
                "order_index": t.order_index or 0,
                "question_count": int(count_map.get(t.id, 0)),
                "theta": theta,
                "mastery": p.mastery_level if p else None,
                # Forgetting curve: ability decayed by idle time since last practice
                "theta_effective": theta_eff,
                "mastery_effective": mastery_eff,
                "days_since_practice": days_idle,
                "attempted": int(p.questions_attempted or 0) if p else 0,
                "correct": int(p.questions_correct or 0) if p else 0,
                "skills": sorted(skills_map.get(t.id, []), key=lambda s: s["kind"]),
            }
        )

    # Edges: learn `from` before `to`
    edge_set: set[tuple[int, int, str]] = set()
    topic_id_set = set(topic_ids)

    prereq_result = await db.execute(
        select(TopicPrerequisite).where(
            TopicPrerequisite.topic_id.in_(topic_ids) if topic_ids else False
        )
    )
    for link in prereq_result.scalars().all():
        if link.prerequisite_topic_id in topic_id_set:
            edge_set.add((link.prerequisite_topic_id, link.topic_id, "prerequisite"))

    kg_result = await db.execute(
        select(KnowledgeGraph)
        .where(KnowledgeGraph.subject_id == subject_id)
        .where(KnowledgeGraph.source_type == "topic")
        .where(KnowledgeGraph.target_type == "topic")
        .where(KnowledgeGraph.relation_type == "prerequisite")
    )
    for edge in kg_result.scalars().all():
        # source requires target (see R12 semantics) -> learn target first
        if edge.target_id in topic_id_set and edge.source_id in topic_id_set:
            edge_set.add((int(edge.target_id), int(edge.source_id), "inference"))

    # Collapse duplicate pairs, preferring the explicit prerequisite relation
    edges_by_pair: dict[tuple[int, int], str] = {}
    for a, b, kind in sorted(edge_set):
        if (a, b) not in edges_by_pair or kind == "prerequisite":
            edges_by_pair[(a, b)] = kind

    return {
        "subject_id": subject_id,
        "subject_name": subject.name,
        "nodes": nodes,
        "edges": [
            {"from": a, "to": b, "type": kind}
            for (a, b), kind in sorted(edges_by_pair.items())
        ],
    }


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
