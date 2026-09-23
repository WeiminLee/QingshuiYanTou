"""Worker 端点的共享鉴权。"""
from __future__ import annotations

from fastapi import HTTPException

from app.config import settings


def require_api_key(key: str | None) -> None:
    expected = settings.knowledge_api_key or settings.api_key
    if not expected or key != expected:
        raise HTTPException(401, "无效 API 密钥")
