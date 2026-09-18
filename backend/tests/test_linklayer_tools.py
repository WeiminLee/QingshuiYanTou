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


def test_link_tools_resolve_and_register():
    """use: 路径必须真实可解析——loader 对 ImportError 只 warning 跳过（loader.py:253-257），
    单独解析 YAML 无法发现路径笔误，必须走 load_tools_from_config() 显式断言注册成功。"""
    from app.reasoning.registry.loader import load_tools_from_config

    configs = load_tools_from_config()
    names = {cfg.name for cfg in configs}
    for name in ("pull_history", "scan_dimension", "lookup_products", "lookup_players", "backlinks"):
        assert name in names, f"loader 未注册工具 {name}（检查 config.yaml 的 use: 路径）"
