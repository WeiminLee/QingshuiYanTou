"""auth_service: 主密码校验、JWT 签发/校验"""
import pytest

from app.account import config as account_cfg
from app.account.services import auth_service


@pytest.fixture
def with_master_pw(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    import app.config
    reload(app.config)


def test_verify_master_password_ok(with_master_pw):
    assert auth_service.verify_master_password("test-master-pass-1234") is True


def test_verify_master_password_wrong(with_master_pw):
    assert auth_service.verify_master_password("wrong") is False


def test_issue_and_verify_token(with_master_pw):
    token = auth_service.issue_master_token()
    assert auth_service.verify_master_token(token) is True


def test_verify_token_tampered(with_master_pw):
    token = auth_service.issue_master_token()
    bad = token[:-2] + ("AB" if token[-2:] != "AB" else "CD")
    assert auth_service.verify_master_token(bad) is False


def test_verify_token_empty(with_master_pw):
    assert auth_service.verify_master_token("") is False
    assert auth_service.verify_master_token(None) is False
