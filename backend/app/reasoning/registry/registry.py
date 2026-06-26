"""
ToolRegistry — 统一工具注册表单例

核心功能：
- register(config, instance)      — 注册工具（YAML 配置 + BaseTool 实例）
- get_tool_instance(name)       — 获取单个工具实例
- get_tool_instances()           — 获取所有已注册工具实例（供 create_agent 使用）
- get_configs()                 — 获取所有工具配置
- get_configs_by_group(group)    — 按分组获取配置
- get_enabled_names()            — 获取已启用的工具名列表
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.reasoning.registry.config import ToolConfig, ToolGroup

logger = logging.getLogger(__name__)

# ── 全局单例 ───────────────────────────────────────────────────────────────

_registry: ToolRegistry | None = None
_registry_lock = threading.RLock()


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ToolRegistry()
    return _registry


# ── 注册表 ────────────────────────────────────────────────────────────────


class ToolRegistry:
    """
    统一工具注册表（线程安全单例）。

    支持两种注册方式：
    1. 代码注册：registry.register(config, instance)
    2. YAML 配置注册：load_tools_from_config(config_list)
    """

    def __init__(self) -> None:
        self._configs: dict[str, ToolConfig] = {}
        self._instances: dict[str, Any] = {}
        self._lock = threading.RLock()

    # ── 基础操作 ───────────────────────────────────────────────────────

    def register(self, config: ToolConfig, instance: Any) -> None:
        """
        注册一个工具。

        Args:
            config: 工具配置（YAML 中定义）
            instance: LangChain BaseTool 实例（@tool 装饰的函数）
        """
        with self._lock:
            if not config.enabled:
                logger.debug(f"[Registry] Tool '{config.name}' is disabled, skipping")
                return
            self._configs[config.name] = config
            self._instances[config.name] = instance
            logger.info(f"[Registry] Registered: {config.name} (group={config.group})")

    def unregister(self, name: str) -> bool:
        """注销一个工具（主要用于测试）"""
        with self._lock:
            if name in self._configs:
                del self._configs[name]
            if name in self._instances:
                del self._instances[name]
                return True
            return False

    def get_config(self, name: str) -> ToolConfig | None:
        """获取工具配置"""
        return self._configs.get(name)

    def get_tool_instance(self, name: str) -> Any | None:
        """获取工具实例"""
        return self._instances.get(name)

    # ── 批量查询 ───────────────────────────────────────────────────────

    def get_configs(self, enabled_only: bool = True) -> list[ToolConfig]:
        """获取所有工具配置"""
        with self._lock:
            configs = list(self._configs.values())
        if enabled_only:
            configs = [c for c in configs if c.enabled]
        return configs

    def get_configs_by_group(self, group: ToolGroup | str) -> list[ToolConfig]:
        """按分组获取配置"""
        with self._lock:
            return [c for c in self._configs.values() if c.enabled and c.group == group]

    def get_enabled_names(self) -> list[str]:
        """获取已启用的工具名列表"""
        with self._lock:
            return [name for name, cfg in self._configs.items() if cfg.enabled]

    def get_tool_instances(self, names: list[str] | None = None) -> list[Any]:
        """
        获取工具实例列表（供 LangChain create_agent 使用）。

        Args:
            names: 如果提供，只返回这些名字的工具；否则返回所有已注册工具
        """
        with self._lock:
            if names is None:
                instances = [
                    inst
                    for name, inst in self._instances.items()
                    if name in self._configs and self._configs[name].enabled
                ]
            else:
                instances = [
                    self._instances[name]
                    for name in names
                    if name in self._instances
                    and self._configs.get(name, None) is not None
                    and self._configs[name].enabled
                ]
        return instances

    def get_group_summary(self) -> dict[str, int]:
        """获取各分组工具数量统计"""
        with self._lock:
            groups: dict[str, int] = {}
            for cfg in self._configs.values():
                if cfg.enabled:
                    groups[cfg.group] = groups.get(cfg.group, 0) + 1
            return groups

    def clear(self) -> None:
        """清空注册表（主要用于测试）"""
        with self._lock:
            self._configs.clear()
            self._instances.clear()
