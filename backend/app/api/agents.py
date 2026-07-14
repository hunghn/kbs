"""Multi-Agent System architecture API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_user
from app.models.user import User
from app.agents.registry import get_architecture

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def get_agent_architecture(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Kiến trúc Multi-Agent của hệ thống: các tác tử, luật chúng sở hữu,
    luồng thông điệp và mức độ hoạt động thực đo từ rule logs."""
    _ = user
    return await get_architecture(db)
