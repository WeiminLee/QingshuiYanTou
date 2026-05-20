"""
tests/test_registry_loader.py — Phase 0: loader.py YAML 声明式改造测试

验证工具注册机制的核心行为（resolve_variable + YAML 配置）。
"""
from __future__ import annotations

import tempfile
import os
from pathlib import Path

import pytest


class TestResolveVariable:
    """resolve_variable 动态导入测试（DeerFlow 风格 use 路径）"""

    def test_resolve_builtin_kline_tool(self):
        """已知存在的工具（get_kline）应能正确导入"""
        from app.reasoning.registry.resolve_variable import resolve_variable

        result = resolve_variable("app.reasoning.tools.market_data.kline:get_kline")
        assert result is not None, "get_kline 工具应能通过 use 路径解析"
        assert callable(result), "解析结果应为可调用对象"

    def test_resolve_invalid_module_raises_import_error(self):
        """不存在的模块路径应抛出 ImportError"""
        from app.reasoning.registry.resolve_variable import resolve_variable

        with pytest.raises(ImportError):
            resolve_variable("app.nonexistent.module:func")

    def test_resolve_invalid_attr_raises_import_error(self):
        """存在模块但属性不存在时应抛出 ImportError"""
        from app.reasoning.registry.resolve_variable import resolve_variable

        with pytest.raises(ImportError):
            resolve_variable("app.reasoning.tools.market_data.kline:nonexistent_func")


class TestLoadToolsFromConfig:
    """load_tools_from_config 加载逻辑测试"""

    def test_yaml_config_preferred_over_defaults(self):
        """当 config.yaml 存在时，应优先从 YAML 加载"""
        from app.reasoning.registry.loader import load_tools_from_config

        configs = load_tools_from_config()
        assert isinstance(configs, list), "应返回配置列表"
        assert len(configs) >= 11, f"应至少加载 11 个现有工具，实际: {len(configs)}"

    def test_all_default_tools_loaded(self):
        """所有 11 个默认工具都应成功加载"""
        from app.reasoning.registry.loader import load_tools_from_config

        configs = load_tools_from_config()
        names = {c.name for c in configs}

        expected = {
            "get_kline",
            "get_concept_hot",
            "get_market_breadth",
            "neo4j_traverse",
            "get_research_report",
            "get_announcement",
            "tavily_search",
            "get_stock_profile",
            "get_irm",
            "present_chart",
            "write_todos",
        }
        missing = expected - names
        assert not missing, f"以下默认工具未加载: {missing}"

    def test_tool_groups_are_correct(self):
        """工具分组应正确映射"""
        from app.reasoning.registry.loader import load_tools_from_config

        configs = load_tools_from_config()
        by_group: dict[str, list[str]] = {}
        for cfg in configs:
            by_group.setdefault(cfg.group, []).append(cfg.name)

        # MARKET_DATA 组应有 K线/板块/宽度工具
        market_tools = by_group.get("market_data", [])
        assert "get_kline" in market_tools, "get_kline 应在 market_data 组"

        # SEARCH 组应有 tavily_search
        search_tools = by_group.get("search", [])
        assert "tavily_search" in search_tools, "tavily_search 应在 search 组"

    def test_provided_configs_used_directly(self):
        """传入 configs 参数时应跳过 YAML，直接使用传入配置"""
        from app.reasoning.registry.loader import load_tools_from_config
        from app.reasoning.registry.config import ToolConfig, ToolGroup

        # 用一个最小配置覆盖
        test_configs = [
            ToolConfig(
                name="test_tool",
                group=ToolGroup.MARKET_DATA,
                use="app.reasoning.tools.market_data.kline:get_kline",
                description="测试工具",
            )
        ]
        result = load_tools_from_config(configs=test_configs)
        names = {c.name for c in result}
        assert "test_tool" in names, "传入的 configs 应被直接使用"
        assert len(result) == 1, "应只返回传入的 1 个工具"

    def test_disabled_tool_not_registered(self):
        """enabled=False 的工具不应被注册"""
        from app.reasoning.registry.loader import load_tools_from_config
        from app.reasoning.registry.config import ToolConfig, ToolGroup

        test_configs = [
            ToolConfig(
                name="disabled_tool",
                group=ToolGroup.MARKET_DATA,
                use="app.reasoning.tools.market_data.kline.get_kline",
                description="禁用工具",
                enabled=False,
            )
        ]
        result = load_tools_from_config(configs=test_configs)
        names = {c.name for c in result}
        assert "disabled_tool" not in names, "disabled_tool 不应被注册"

    def test_load_nonexistent_tool_returns_others(self):
        """某个工具导入失败时，不应阻断其他工具加载"""
        from app.reasoning.registry.loader import load_tools_from_config
        from app.reasoning.registry.config import ToolConfig, ToolGroup

        test_configs = [
            ToolConfig(
                name="good_tool",
                group=ToolGroup.MARKET_DATA,
                use="app.reasoning.tools.market_data.kline:get_kline",
                description="有效工具",
            ),
            ToolConfig(
                name="bad_tool",
                group=ToolGroup.SEARCH,
                use="app.reasoning.tools.nonexistent.module:func",
                description="无效工具",
            ),
        ]
        result = load_tools_from_config(configs=test_configs)
        names = {c.name for c in result}
        assert "good_tool" in names, "有效工具应被加载"
        assert "bad_tool" not in names, "导入失败的工具不应被注册"


class TestYamlConfigFile:
    """config.yaml 文件格式测试"""

    def test_yaml_file_exists_or_fallback(self):
        """config.yaml 存在则使用，不存在则 fallback 到内嵌默认值"""
        from app.reasoning.registry.loader import _CONFIG_PATH, load_tools_from_config

        if _CONFIG_PATH.exists():
            # YAML 存在时，至少加载 11 个工具
            configs = load_tools_from_config()
            assert len(configs) >= 11
        else:
            # YAML 不存在时，也应加载 11 个默认工具（fallback）
            configs = load_tools_from_config()
            assert len(configs) >= 11

    def test_yaml_syntax_valid(self):
        """如果 config.yaml 存在，YAML 语法应有效"""
        from app.reasoning.registry.loader import _CONFIG_PATH

        if not _CONFIG_PATH.exists():
            pytest.skip("config.yaml 不存在，跳过语法验证")

        import yaml

        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert "tools" in data, "YAML 应包含 tools 列表"
        assert isinstance(data["tools"], list), "tools 应为列表"
        for tool in data["tools"]:
            assert "name" in tool, f"工具条目缺少 name: {tool}"
            assert "use" in tool, f"工具条目缺少 use: {tool}"
            assert "group" in tool, f"工具条目缺少 group: {tool}"

    def test_new_tools_in_yaml(self):
        """config.yaml 应包含新增工具：web_fetch, read_file, write_file, ls, ask_clarification"""
        from app.reasoning.registry.loader import _CONFIG_PATH

        if not _CONFIG_PATH.exists():
            pytest.skip("config.yaml 不存在")

        import yaml

        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        names = {t["name"] for t in data["tools"]}
        expected_new = {"web_fetch", "read_file", "write_file", "ls", "ask_clarification"}
        missing = expected_new - names
        assert not missing, f"以下新增工具未在 config.yaml 中声明: {missing}"
