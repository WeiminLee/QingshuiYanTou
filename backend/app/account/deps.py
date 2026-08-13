"""FastAPI Depends：用户态接口的鉴权"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.services import auth_service
from app.core.database import get_db


async def verify_master_token(request: Request) -> None:
    """校验 master_token cookie；失败 401"""
    token = request.cookies.get("master_token")
    if not auth_service.verify_master_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话失效",
        )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """从 user_id cookie 取当前用户；失败 401"""
    from app.account.services import user_service

    user_id = request.cookies.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未选择身份",
        )
    try:
        user = await user_service.get_active(db, user_id)
    except Exception:
        # 空库/无 PostgreSQL 降级：用 users.yaml 校验身份，返回轻量用户对象。
        from types import SimpleNamespace

        from app.account import config as account_cfg

        yaml_users = account_cfg.load_users_from_yaml()
        match = next((u for u in yaml_users if u.user_id == user_id), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="身份无效或已停用",
            )
        return SimpleNamespace(user_id=match.user_id, display_name=match.display_name, is_active=True)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="身份无效或已停用",
        )
    return user
