"""Pydantic schemas 的字段和校验"""

import pytest
from pydantic import ValidationError

from app.account.schemas import (
    LoginRequest,
    PortfolioAddRequest,
    SwitchUserRequest,
)


def test_login_request():
    obj = LoginRequest(password="abc12345")
    assert obj.password == "abc12345"


def test_login_request_too_short():
    with pytest.raises(ValidationError):
        LoginRequest(password="")


def test_switch_user_request():
    obj = SwitchUserRequest(user_id="alice")
    assert obj.user_id == "alice"


def test_portfolio_add_request_ts_code_format():
    # 合法
    PortfolioAddRequest(ts_code="600519.SH")
    # 缺 .SZ/.SH 等后缀
    with pytest.raises(ValidationError):
        PortfolioAddRequest(ts_code="600519")
