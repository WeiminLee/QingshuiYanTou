"""工具注册测试：config.yaml 可解析 + 工具函数可调用。"""
import yaml


def test_registry_has_link_tools():
    from pathlib import Path
    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "app" / "reasoning" / "registry" / "config.yaml")
        .read_text(encoding="utf-8")
    )
    names = {t["name"] for t in cfg["tools"]}
    for name in ("pull_history", "scan_dimension", "lookup_products", "lookup_players", "backlinks"):
        assert name in names, f"registry 缺少工具 {name}"


def test_pull_history_tool_importable():
    from app.reasoning.tools.knowledge.link_queries import pull_history_tool
    assert pull_history_tool.name == "pull_history"
