"""
tools/tools.py — 统一工具加载机制（DeerFlow 风格）

参考 DeerFlow deerflow/tools/tools.py:
- get_available_tools() 函数整合配置工具 + 内置工具
- BUILTIN_TOOLS 列表包含 ask_clarification 等内置工具
- 支持 groups 过滤、subagent_enabled 开关

与 registry 的分工：
- registry: 从 YAML/默认配置加载业务工具（get_kline, tavily_search 等）
- tools.py: 整合业务工具 + 内置工具（ask_clarification, present_file 等）
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from app.reasoning.langchain_agent.skills.skill_manage import WriteSkillTool
from app.reasoning.langchain_agent.skills.tools import skill_view_tool, skills_list_tool
from app.reasoning.registry import get_registry, load_tools_from_config
from app.reasoning.tools.builtins import ask_clarification, ask_user_question
from app.reasoning.tools.builtins.task import task_tool
from app.reasoning.tools.guardrails import validate_tool_boundary
from app.reasoning.tools.registry import get_tool_health_registry

logger = logging.getLogger(__name__)

# ── 内置工具列表（始终包含）──────────────────────────────────────

BUILTIN_TOOLS: list[BaseTool] = [
    ask_user_question,  # 统一提问工具（推荐使用）
    ask_clarification,  # 保留兼容（旧格式自动转换）
    skills_list_tool,   # 列出所有可用 skill
    skill_view_tool,    # 加载指定 skill 完整内容
    WriteSkillTool(),  # agent 自我进化：创建自定义 skill
]

# SubAgent 工具（仅 subagent_enabled=True 时包含）
SUBAGENT_TOOLS: list[BaseTool] = [task_tool]


def get_available_tools(
    groups: list[str] | None = None,
    include_builtin: bool = True,
    subagent_enabled: bool = False,
) -> list[BaseTool]:
    """
    获取所有可用工具（DeerFlow 风格）。

    整合：
    1. Registry 配置工具（get_kline, tavily_search 等）
    2. 内置工具（ask_clarification 等）

    Args:
        groups: 可选，按分组过滤工具（如 ["market_data", "knowledge"]）
        include_builtin: 是否包含内置工具（默认 True）
        subagent_enabled: 是否包含 SubAgent 工具（task 等）

    Returns:
        LangChain BaseTool 实例列表，供 create_agent 使用
    """
    # 确保注册表已加载
    registry = get_registry()
    if not registry.get_configs():
        load_tools_from_config()

    # 从注册表获取业务工具
    if groups is not None:
        # 按分组过滤
        loaded_tools = []
        for name in registry.get_enabled_names():
            cfg = registry.get_config(name)
            if cfg and cfg.group in groups:
                inst = registry.get_tool_instance(name)
                if inst:
                    validate_tool_boundary(getattr(inst, "name", name), getattr(inst, "description", ""))
                    loaded_tools.append(inst)
    else:
        loaded_tools = registry.get_tool_instances()
        for tool in loaded_tools:
            validate_tool_boundary(getattr(tool, "name", ""), getattr(tool, "description", ""))

    # 收集已加载的工具名称（用于去重）
    loaded_names = {t.name for t in loaded_tools}

    # 内置工具（排除已在注册表中的）
    builtin_tools: list[BaseTool] = []
    if include_builtin:
        for tool in BUILTIN_TOOLS:
            if tool.name not in loaded_names:
                validate_tool_boundary(tool.name, getattr(tool, "description", ""))
                builtin_tools.append(tool)

    # SubAgent 工具（条件添加）
    if subagent_enabled:
        for tool in SUBAGENT_TOOLS:
            if tool.name not in loaded_names and tool not in builtin_tools:
                validate_tool_boundary(tool.name, getattr(tool, "description", ""))
                builtin_tools.append(tool)
        logger.info("[Tools] Including subagent tools")

    all_tools = loaded_tools + builtin_tools
    health = get_tool_health_registry()
    for tool in all_tools:
        health.register(tool)

    logger.info(
        f"[Tools] get_available_tools: {len(loaded_tools)} from registry, "
        f"{len(builtin_tools)} builtin, total={len(all_tools)}"
    )

    return all_tools


def get_tool_by_name(name: str) -> BaseTool | None:
    """
    按名称获取单个工具实例。

    Args:
        name: 工具名称

    Returns:
        BaseTool 实例或 None
    """
    # 先查注册表
    inst = get_registry().get_tool_instance(name)
    if inst:
        return inst

    # 再查内置工具
    for tool in BUILTIN_TOOLS:
        if tool.name == name:
            return tool

    return None


def get_all_tool_names() -> list[str]:
    """获取所有工具名称列表（用于调试/日志）"""
    tools = get_available_tools()
    return [t.name for t in tools]
