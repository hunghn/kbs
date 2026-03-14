from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.models.system_config import LLMRuntimeConfig
from pathlib import Path


DEFAULT_LLM_RUNTIME_CONFIG = {
    "llm_enabled": True,
    "cat_enable_hybrid_llm_on_answer": False,
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-5.1",
    "llm_temperature": 0.2,
    "llm_timeout_seconds": 30,
}


def _load_default_system_prompt() -> str:
    settings = get_settings()
    configured = Path(settings.LLM_SYSTEM_PROMPT_PATH)

    candidates = []
    if configured.is_absolute():
        candidates.append(configured)
    else:
        cwd = Path.cwd()
        candidates.append(cwd / configured)
        candidates.append(cwd.parent / configured)

    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()

    return (
        "Bạn là trợ lý tạo câu hỏi trắc nghiệm theo IRT 3PL. "
        "Luôn trả JSON hợp lệ với các trường stem, option_a, option_b, option_c, option_d, correct_answer, "
        "difficulty_b, discrimination_a, guessing_c, explanation."
    )


async def get_effective_llm_runtime_config(db: AsyncSession) -> dict:
    settings = get_settings()
    default_system_prompt = _load_default_system_prompt()

    result = await db.execute(
        select(LLMRuntimeConfig).where(LLMRuntimeConfig.id == 1)
    )
    row = result.scalar_one_or_none()

    if not row:
        row = LLMRuntimeConfig(
            id=1,
            llm_api_key=settings.LLM_API_KEY,
            llm_system_prompt=default_system_prompt,
            **DEFAULT_LLM_RUNTIME_CONFIG,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    else:
        changed = False
        if not row.llm_api_key and settings.LLM_API_KEY:
            row.llm_api_key = settings.LLM_API_KEY
            changed = True
        if not row.llm_system_prompt:
            row.llm_system_prompt = default_system_prompt
            changed = True

        if changed:
            await db.commit()
            await db.refresh(row)

    return {
        "llm_enabled": bool(row.llm_enabled),
        "cat_enable_hybrid_llm_on_answer": bool(row.cat_enable_hybrid_llm_on_answer),
        "llm_api_key": row.llm_api_key,
        "has_llm_api_key": bool(row.llm_api_key),
        "llm_system_prompt": row.llm_system_prompt,
        "llm_base_url": row.llm_base_url,
        "llm_model": row.llm_model,
        "llm_temperature": float(row.llm_temperature),
        "llm_timeout_seconds": int(row.llm_timeout_seconds),
    }
