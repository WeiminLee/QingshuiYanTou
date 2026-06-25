"""/api/v1/users 路由：列出可选身份"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.deps import verify_master_token
from app.account.schemas import UserBrief, UserBriefList
from app.account.services import user_service
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/users", tags=["account"])


@router.get("", response_model=UserBriefList)
async def list_users(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_master_token),
) -> UserBriefList:
    users = await user_service.list_active(db)
    return UserBriefList(users=[UserBrief.model_validate(u) for u in users])
