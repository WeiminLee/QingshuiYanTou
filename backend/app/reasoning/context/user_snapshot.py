from __future__ import annotations

from typing import Any

from app.reasoning.context.schemas import UserSnapshotDTO
from app.reasoning.langchain_agent.memory.user_memory_provider import PREF_COLLECTION


async def _list_portfolio(user_id: str):
    from app.account.services.portfolio_service import list_for_user
    from app.core.database import async_session

    async with async_session() as session:
        return await list_for_user(session, user_id)


def _get_collection(name: str):
    from app.core.mongodb import get_mongo_db

    return get_mongo_db()[name]


async def build_user_snapshot(user_id: str) -> tuple[UserSnapshotDTO, list[str]]:
    warnings: list[str] = []
    portfolio: list[dict[str, Any]] = []
    preferences: list[dict[str, Any]] = []

    try:
        rows = await _list_portfolio(user_id)
        for row in rows:
            portfolio.append(
                {
                    "ts_code": str(getattr(row, "ts_code", "") or ""),
                    "name": str(getattr(row, "stock_name", "") or getattr(row, "name", "") or ""),
                }
            )
    except Exception:
        warnings.append("portfolio_read_failed")

    try:
        doc = await _get_collection(PREF_COLLECTION).find_one({"user_id": user_id})
        preferences = list((doc or {}).get("items", []) or [])
    except Exception:
        warnings.append("preferences_read_failed")

    return UserSnapshotDTO(user_id=user_id, portfolio=portfolio, preferences=preferences), warnings
