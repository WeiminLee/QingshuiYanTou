"""只读借用 account 模块的持仓，供 prefetch 注入。失败静默降级。"""

from __future__ import annotations

import logging

from app.account.services.portfolio_service import list_for_user as _list_for_user
from app.core.database import async_session

logger = logging.getLogger(__name__)


async def fetch_portfolio_lines(user_id: str) -> list[str]:
    """返回 ["名称(ts_code)", ...]；任何异常降级为 []。"""
    try:
        async with async_session() as session:
            positions = await _list_for_user(session, user_id)
        return [f"{p.stock_name}({p.ts_code})" for p in positions]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portfolio_reader] 读取持仓失败 [%s]: %s", user_id, exc)
        return []
