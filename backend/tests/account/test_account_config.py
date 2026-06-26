"""测试 account 子包的 config：yaml 加载、token 盐派生、主密码校验"""

import pytest

from app.account import config as account_cfg


def test_load_users_from_yaml(temp_users_yaml):
    users = account_cfg.load_users_from_yaml(temp_users_yaml)
    assert [u.user_id for u in users] == ["alice", "bob"]
    assert users[0].display_name == "Alice"


def test_load_users_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        account_cfg.load_users_from_yaml(tmp_path / "no-such.yaml")


def test_derive_token_secret(master_password_env):
    secret = account_cfg.derive_token_secret()
    assert isinstance(secret, str) and len(secret) >= 32
    # 同一进程派生稳定
    assert account_cfg.derive_token_secret() == secret


def test_validate_master_password_ok(master_password_env):
    account_cfg.validate_master_password()  # 不抛


def test_validate_master_password_too_short(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "short")
    from importlib import reload

    import app.config

    reload(app.config)
    with pytest.raises(ValueError, match="长度"):
        account_cfg.validate_master_password()
