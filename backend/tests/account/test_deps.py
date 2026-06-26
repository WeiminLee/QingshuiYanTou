"""FastAPI Depends: verify_master_token + get_current_user"""

import pytest
from fastapi import HTTPException

from app.account import deps as account_deps


class _FakeRequest:
    def __init__(self, cookies: dict | None = None):
        self.cookies = cookies or {}


@pytest.mark.asyncio
async def test_verify_master_token_ok(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload

    import app.config

    reload(app.config)
    from app.account.services import auth_service

    token = auth_service.issue_master_token()
    await account_deps.verify_master_token(_FakeRequest({"master_token": token}))  # 不抛


@pytest.mark.asyncio
async def test_verify_master_token_missing(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload

    import app.config

    reload(app.config)
    with pytest.raises(HTTPException) as ei:
        await account_deps.verify_master_token(_FakeRequest({}))
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_no_cookie(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload

    import app.config

    reload(app.config)
    with pytest.raises(HTTPException) as ei:
        # db won't be reached because cookie check happens first
        await account_deps.get_current_user(_FakeRequest({}), None)
    assert ei.value.status_code == 401
