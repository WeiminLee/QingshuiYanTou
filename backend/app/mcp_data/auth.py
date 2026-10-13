"""API key auth for Data MCP HTTP transport (same secret as Knowledge)."""
from __future__ import annotations

import os


def expected_api_key() -> str:
    """Prefer env so MCP can start without full backend .env validation."""
    for name in ("KNOWLEDGE_API_KEY", "API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    try:
        from app.config import settings

        return (settings.knowledge_api_key or settings.api_key or "").strip()
    except Exception:  # noqa: BLE001 — missing .env is OK for env-only deploys
        return ""


def validate_api_key(key: str | None) -> bool:
    expected = expected_api_key()
    if not expected:
        return False
    return (key or "").strip() == expected
