"""Sub-Project 1 测试 fixtures"""
from pathlib import Path
import pytest


@pytest.fixture
def temp_users_yaml(tmp_path):
    """临时 yaml 路径，内容是示例用户"""
    yaml_path = tmp_path / "users.yaml"
    yaml_path.write_text(
        "users:\n"
        "  - user_id: alice\n"
        "    display_name: Alice\n"
        "  - user_id: bob\n"
        "    display_name: Bob\n",
        encoding="utf-8",
    )
    return yaml_path


@pytest.fixture
def master_password_env(monkeypatch):
    """保证主密码满足长度要求，重新加载 settings"""
    monkeypatch.setenv("MASTER_PASSWORD", "test-master-pass-1234")
    from importlib import reload
    import app.config
    reload(app.config)
    return "test-master-pass-1234"
