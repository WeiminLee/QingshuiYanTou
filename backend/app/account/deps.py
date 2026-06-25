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
    user = await user_service.get_active(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="身份无效或已停用",
        )
    return user
