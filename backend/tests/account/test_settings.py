"""验证 Sub-Project 1 相关的 settings 字段被正确加载"""


def test_master_password_loaded(monkeypatch):
    monkeypatch.setenv("MASTER_PASSWORD", "test-pass-1234")
    # 重新加载 settings（避免 cache）
    from importlib import reload

    from app import config as cfg_mod

    reload(cfg_mod)
    assert cfg_mod.settings.master_password == "test-pass-1234"


def test_users_yaml_path_default_exists():
    from app.config import settings

    assert settings.users_yaml_path.name == "users.yaml"
    assert settings.users_yaml_path.exists()
