"""
Import knowledge matrix from MaTranKienThuc.xlsx into the database.
Handles data cleaning and builds the ontology tree:
  Subject -> MajorTopic -> Topic -> Question
"""
import re
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from app.config import get_settings
from app.models.knowledge import Subject, MajorTopic, Topic, TopicPrerequisite
from app.models.question import Question
from app.models.cat_knowledge import KnowledgeGraph
from app.database import Base


def clean_difficulty(val) -> float:
    """Convert difficulty value to float, handling bad data."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def clean_answer(val: str) -> str:
    """Clean answer value to single character A/B/C/D."""
    if not val or not isinstance(val, str):
        return "A"
    # Handle cases like "B)$" -> "B"
    cleaned = val.strip().upper()
    if cleaned and cleaned[0] in "ABCD":
        return cleaned[0]
    return "A"


def clean_question_type(val: str) -> str:
    """Normalize question type to one of: Nhận biết, Thông hiểu, Vận dụng."""
    valid_types = {"Nhận biết", "Thông hiểu", "Vận dụng"}
    if isinstance(val, str) and val.strip() in valid_types:
        return val.strip()
    return "Nhận biết"  # default fallback


def parse_time_seconds(val) -> int:
    """Parse 'Thời gian dự kiến (giây)' to int."""
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 60


def extract_code(name: str) -> str:
    """Extract code from names like '1.1 Logic mệnh đề' -> '1.1'."""
    match = re.match(r"^(\d+\.?\d*)", name.strip())
    return match.group(1) if match else ""


def import_excel(excel_path: str, db_url: str = None):
    """Main import function - reads Excel and populates database."""
    settings = get_settings()
    url = db_url or settings.DATABASE_URL_SYNC
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)

    xl = pd.ExcelFile(excel_path)

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        for sheet_name in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=sheet_name)
            _import_sheet(session, df, sheet_name)
        session.commit()
        print("Import completed successfully!")


def _import_sheet(session: Session, df: pd.DataFrame, sheet_name: str):
    """Import a single sheet into the database."""
    subject_name = df["Môn học"].iloc[0] if "Môn học" in df.columns else sheet_name

    # Create or get Subject
    subject = session.query(Subject).filter_by(name=subject_name).first()
    if not subject:
        subject = Subject(name=subject_name, description=f"Imported from {sheet_name}")
        session.add(subject)
        session.flush()
        print(f"  Created subject: {subject_name}")

    # Build major_topic -> topic -> questions hierarchy
    major_topic_cache = {}
    topic_cache = {}

    for _, row in df.iterrows():
        mt_name = str(row.get("Chủ đề lớn", "")).strip()
        t_name = str(row.get("Kiến thức liên quan", "")).strip()

        if not mt_name or mt_name == "nan":
            continue

        # Create/get MajorTopic
        if mt_name not in major_topic_cache:
            mt = session.query(MajorTopic).filter_by(
                subject_id=subject.id, name=mt_name
            ).first()
            if not mt:
                mt_code = extract_code(mt_name)
                mt = MajorTopic(
                    subject_id=subject.id,
                    code=mt_code,
                    name=mt_name,
                    order_index=len(major_topic_cache),
                )
                session.add(mt)
                session.flush()
                print(f"    Created major topic: {mt_name}")
            major_topic_cache[mt_name] = mt

        mt = major_topic_cache[mt_name]

        # Create/get Topic
        topic_key = f"{mt_name}::{t_name}"
        if topic_key not in topic_cache:
            topic = session.query(Topic).filter_by(
                major_topic_id=mt.id, name=t_name
            ).first()
            if not topic:
                t_code = extract_code(t_name)
                topic = Topic(
                    major_topic_id=mt.id,
                    code=t_code,
                    name=t_name,
                    order_index=len(topic_cache),
                )
                session.add(topic)
                session.flush()
                print(f"      Created topic: {t_name}")

                edge = session.query(KnowledgeGraph).filter_by(
                    subject_id=subject.id,
                    source_type="major_topic",
                    source_id=mt.id,
                    target_type="topic",
                    target_id=topic.id,
                    relation_type="parent_child",
                ).first()
                if not edge:
                    session.add(
                        KnowledgeGraph(
                            subject_id=subject.id,
                            source_type="major_topic",
                            source_id=mt.id,
                            target_type="topic",
                            target_id=topic.id,
                            relation_type="parent_child",
                        )
                    )
            topic_cache[topic_key] = topic

        topic = topic_cache[topic_key]

        # Create Question
        ext_id = str(row.get("ID", "")).strip()
        if not ext_id or ext_id == "nan":
            continue

        existing = session.query(Question).filter_by(external_id=ext_id).first()
        if existing:
            continue

        question = Question(
            external_id=ext_id,
            topic_id=topic.id,
            stem=str(row.get("Nội dung câu hỏi (Stem)", "")),
            option_a=str(row.get("Đáp án A", "")),
            option_b=str(row.get("Đáp án B", "")),
            option_c=str(row.get("Đáp án C", "")),
            option_d=str(row.get("Đáp án D", "")),
            correct_answer=clean_answer(str(row.get("Đáp án đúng", "A"))),
            difficulty_b=clean_difficulty(row.get("Độ khó (b)", 0)),
            discrimination_a=clean_difficulty(row.get("Độ phân biệt (a)", 1)),
            guessing_c=clean_difficulty(row.get("Đoán mò (c)", 0.25)),
            question_type=clean_question_type(str(row.get("Dạng câu hỏi", ""))),
            time_limit_seconds=parse_time_seconds(row.get("Thời gian dự kiến (giây)", 60)),
            time_display=str(row.get("Thời gian hiển thị (MM:SS)", "01:00")),
        )
        session.add(question)

    session.flush()
    _build_default_prerequisites(session, subject.id)
    print(f"  Sheet '{sheet_name}' imported.")


def _build_default_prerequisites(session: Session, subject_id: int):
    """Create default prerequisite chain by topic code/order within each major topic."""
    major_topics = session.query(MajorTopic).filter_by(subject_id=subject_id).all()
    for mt in major_topics:
        topics = session.query(Topic).filter_by(major_topic_id=mt.id).all()
        topics_sorted = sorted(
            topics,
            key=lambda t: (t.code or "", t.order_index, t.id),
        )
        for idx in range(1, len(topics_sorted)):
            curr = topics_sorted[idx]
            prev = topics_sorted[idx - 1]

            exists = session.query(TopicPrerequisite).filter_by(
                topic_id=curr.id,
                prerequisite_topic_id=prev.id,
            ).first()
            if not exists:
                session.add(
                    TopicPrerequisite(
                        topic_id=curr.id,
                        prerequisite_topic_id=prev.id,
                    )
                )

            edge = session.query(KnowledgeGraph).filter_by(
                subject_id=subject_id,
                source_type="topic",
                source_id=curr.id,
                target_type="topic",
                target_id=prev.id,
                relation_type="prerequisite",
            ).first()
            if not edge:
                session.add(
                    KnowledgeGraph(
                        subject_id=subject_id,
                        source_type="topic",
                        source_id=curr.id,
                        target_type="topic",
                        target_id=prev.id,
                        relation_type="prerequisite",
                    )
                )


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "../MaTranKienThuc.xlsx"
    import_excel(path)
