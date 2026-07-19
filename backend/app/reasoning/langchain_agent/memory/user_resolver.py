"""user_id 解析：缺省回退默认用户。集中此处便于将来收紧为必填。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FALLBACK = "default"


def _load_users() -> list:
    """读取 users.yaml 解析出的用户列表。失败返回空列表。"""
    try:
        from app.account.config import load_users_from_yaml

        return list(load_users_from_yaml())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[user_resolver] 加载 users 失败: %s", exc)
        return []


def _default_user_id() -> str:
    users = _load_users()
    if not users:
        return _FALLBACK
    first = users[0]
    return getattr(first, "user_id", None) or _FALLBACK


def resolve_user_id(user_id: str | None) -> str:
    if user_id and user_id.strip():
        return user_id.strip()
    return _default_user_id()
