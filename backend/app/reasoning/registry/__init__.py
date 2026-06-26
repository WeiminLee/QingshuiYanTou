"""
Registry — 统一 Tool 注册表（DeerFlow 风格）

提供：
- ToolConfig Pydantic 模型（YAML 配置结构）
- ToolRegistry 单例（工具注册/发现/加载）
- YAML 配置加载器（支持 resolve_variable 动态导入）
- resolve_variable 工具解析器（支持环境变量插值）

使用方式：
    from app.reasoning.registry import get_registry, get_all_tools
    registry = get_registry()
    tools = get_all_tools()
"""

from app.reasoning.registry.config import ToolConfig, ToolGroup
from app.reasoning.registry.loader import load_tools_from_config
from app.reasoning.registry.registry import ToolRegistry, get_registry
from app.reasoning.registry.resolve_variable import resolve_class, resolve_variable

__all__ = [
    "ToolConfig",
    "ToolGroup",
    "ToolRegistry",
    "get_registry",
    "load_tools_from_config",
    "resolve_variable",
    "resolve_class",
    "get_all_tools",
]


def get_all_tools() -> list:
    """
    返回所有已注册工具的 LangChain BaseTool 实例。
    供 create_agent 使用。
    """
    return get_registry().get_tool_instances()
