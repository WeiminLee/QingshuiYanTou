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
    try:
        users = await user_service.list_active(db)
        briefs = [UserBrief.model_validate(u) for u in users]
    except Exception:
        # 空库/无 PostgreSQL 降级：从 users.yaml 读取可选身份，保证选择身份页可用。
        from app.account import config as account_cfg

        yaml_users = account_cfg.load_users_from_yaml()
        briefs = [UserBrief(user_id=u.user_id, display_name=u.display_name) for u in yaml_users]
    return UserBriefList(users=briefs)
