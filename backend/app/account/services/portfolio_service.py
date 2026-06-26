"""持仓服务：增删查，严格按 user_id 隔离"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import PortfolioPosition


async def add(session: AsyncSession, user_id: str, ts_code: str, stock_name: str) -> PortfolioPosition:
    """添加持仓；重复抛 IntegrityError（让上层映射 409）"""
    pos = PortfolioPosition(user_id=user_id, ts_code=ts_code, stock_name=stock_name)
    session.add(pos)
    await session.commit()
    await session.refresh(pos)
    return pos


async def list_for_user(session: AsyncSession, user_id: str) -> list[PortfolioPosition]:
    """列出某用户的所有持仓，按 created_at desc"""
    result = await session.execute(
        select(PortfolioPosition)
        .where(PortfolioPosition.user_id == user_id)
        .order_by(PortfolioPosition.created_at.desc())
    )
    return list(result.scalars())


async def remove(session: AsyncSession, user_id: str, ts_code: str) -> bool:
    """删除持仓；只删自己的，删别人的返回 False（不抛错，路由层映射 404）"""
    result = await session.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.user_id == user_id,
            PortfolioPosition.ts_code == ts_code,
        )
    )
    pos = result.scalar_one_or_none()
    if pos is None:
        return False
    await session.delete(pos)
    await session.commit()
    return True
