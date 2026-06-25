"""用户服务：yaml 同步 + 活跃查询"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account import config as account_cfg
from app.models.models import User


async def sync_from_yaml(session: AsyncSession, yaml_path: Path | None = None) -> int:
    """根据 yaml 同步到 DB：
    - 新出现的 user_id: 插入，is_active=true
    - 已存在的 user_id: 更新 display_name、updated_at
    - yaml 中不存在的 user_id: 置 is_active=false
    返回活跃用户数。
    """
    yaml_users = account_cfg.load_users_from_yaml(yaml_path)
    yaml_ids = {u.user_id for u in yaml_users}

    for yu in yaml_users:
        existing = await session.get(User, yu.user_id)
        if existing is None:
            session.add(User(user_id=yu.user_id, display_name=yu.display_name, is_active=True))
        else:
            existing.display_name = yu.display_name
            existing.is_active = True
    result = await session.execute(select(User))
    for row in result.scalars():
        if row.user_id not in yaml_ids:
            row.is_active = False
    await session.commit()

    active_q = await session.execute(select(User).where(User.is_active.is_(True)))
    return len(list(active_q.scalars()))


async def get_active(session: AsyncSession, user_id: str) -> Optional[User]:
    """返回活跃用户；不存在或已停用返回 None"""
    u = await session.get(User, user_id)
    if u is None or not u.is_active:
        return None
    return u


async def list_active(session: AsyncSession) -> list[User]:
    """所有活跃用户"""
    result = await session.execute(select(User).where(User.is_active.is_(True)).order_by(User.user_id))
    return list(result.scalars())
