"""Exam builder API (teacher/admin): draft -> review -> save as preset."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.services.runtime_settings import get_effective_llm_runtime_config

router = APIRouter(prefix="/api/quiz/presets", tags=["exam-builder"])


class BuildDraftIn(BaseModel):
    subject_id: int
    topic_ids: list[int] | None = None
    # Số câu theo từng dạng
    mcq: int = Field(default=0, ge=0, le=50)
    true_false: int = Field(default=0, ge=0, le=50)
    short_answer: int = Field(default=0, ge=0, le=50)
    matching: int = Field(default=0, ge=0, le=20)
    recognition_pct: float = 0.3
    comprehension_pct: float = 0.5
    application_pct: float = 0.2
    anchor_mode: str = "manual"      # manual | learners
    target_b: float | None = None
    use_llm: bool = True


class GenerateOneIn(BaseModel):
    subject_id: int
    topic_id: int
    question_format: str = "mcq"
    bloom: str = "Thông hiểu"
    target_b: float | None = None


class SavePresetIn(BaseModel):
    subject_id: int
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    question_ids: list[int]
    discarded_generated_ids: list[int] = []


@router.post("/build")
async def build_exam_draft(
    payload: BuildDraftIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dựng đề nháp: lấy từ ngân hàng trước, LLM sinh bù phần thiếu; mỗi câu
    sinh ra kèm báo cáo kiểm soát chất lượng (self-check + Gemini)."""
    _ = user
    from app.services.exam_builder import build_draft

    runtime_settings = await get_effective_llm_runtime_config(db)
    try:
        draft = await build_draft(
            db,
            subject_id=payload.subject_id,
            topic_ids=payload.topic_ids,
            format_counts={
                "mcq": payload.mcq,
                "true_false": payload.true_false,
                "short_answer": payload.short_answer,
                "matching": payload.matching,
            },
            bloom_pcts={
                "recognition": payload.recognition_pct,
                "comprehension": payload.comprehension_pct,
                "application": payload.application_pct,
            },
            anchor_mode=payload.anchor_mode,
            target_b=payload.target_b,
            use_llm=payload.use_llm,
            runtime_settings=runtime_settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()
    return draft


@router.post("/generate-one")
async def generate_one_question(
    payload: GenerateOneIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sinh lại một câu (dạng + Bloom + độ khó chỉ định) cho đề nháp."""
    _ = user
    from app.services.exam_builder import generate_one_item, SUPPORTED_FORMATS

    if payload.question_format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail="Dạng câu hỏi không hỗ trợ")

    runtime_settings = await get_effective_llm_runtime_config(db)
    try:
        item = await generate_one_item(
            db,
            subject_id=payload.subject_id,
            topic_id=payload.topic_id,
            fmt=payload.question_format,
            bloom=payload.bloom,
            target_b=payload.target_b,
            runtime_settings=runtime_settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()
    return item


@router.post("/save")
async def save_exam_preset(
    payload: SavePresetIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lưu đề đã duyệt thành đề có sẵn; câu LLM được giữ sẽ vào ngân hàng."""
    _ = user
    from app.services.exam_builder import save_preset

    try:
        return await save_preset(
            db,
            subject_id=payload.subject_id,
            name=payload.name,
            description=payload.description,
            question_ids=payload.question_ids,
            discarded_generated_ids=payload.discarded_generated_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
