from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.models.system_config import LLMRuntimeConfig
from app.schemas.admin import LLMRuntimeConfigOut, LLMRuntimeConfigUpdate
from app.services.runtime_settings import get_effective_llm_runtime_config

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/settings/llm", response_model=LLMRuntimeConfigOut)
async def get_llm_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    data = await get_effective_llm_runtime_config(db)
    return LLMRuntimeConfigOut(**data)


@router.put("/settings/llm", response_model=LLMRuntimeConfigOut)
async def update_llm_settings(
    payload: LLMRuntimeConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user

    result = await db.execute(
        select(LLMRuntimeConfig).where(LLMRuntimeConfig.id == 1)
    )
    row = result.scalar_one_or_none()
    if not row:
        row = LLMRuntimeConfig(id=1)
        db.add(row)

    row.llm_enabled = payload.llm_enabled
    row.cat_enable_hybrid_llm_on_answer = payload.cat_enable_hybrid_llm_on_answer
    if payload.llm_api_key is not None and payload.llm_api_key.strip():
        row.llm_api_key = payload.llm_api_key.strip()
    row.llm_system_prompt = payload.llm_system_prompt.strip()
    row.llm_base_url = payload.llm_base_url
    row.llm_model = payload.llm_model
    row.llm_temperature = payload.llm_temperature
    row.llm_timeout_seconds = payload.llm_timeout_seconds

    await db.commit()
    await db.refresh(row)

    return LLMRuntimeConfigOut(
        llm_enabled=row.llm_enabled,
        cat_enable_hybrid_llm_on_answer=row.cat_enable_hybrid_llm_on_answer,
        has_llm_api_key=bool(row.llm_api_key),
        llm_system_prompt=row.llm_system_prompt,
        llm_base_url=row.llm_base_url,
        llm_model=row.llm_model,
        llm_temperature=float(row.llm_temperature),
        llm_timeout_seconds=row.llm_timeout_seconds,
    )
