"""Lightweight tool health registry for reasoning tools."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolHealth:
    name: str
    available: bool
    checked_at: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolHealthRegistry:
    """TTL-cached availability metadata for LangChain tools."""

    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl_seconds = ttl_seconds
        self._tools: dict[str, Any] = {}
        self._health: dict[str, ToolHealth] = {}

    def register(self, tool: Any) -> None:
        name = getattr(tool, "name", "")
        if name:
            self._tools[name] = tool

    def check(self, name: str, *, force: bool = False) -> ToolHealth:
        now = time.time()
        cached = self._health.get(name)
        if cached and not force and now - cached.checked_at < self.ttl_seconds:
            return cached

        tool = self._tools.get(name)
        if tool is None:
            health = ToolHealth(name=name, available=False, checked_at=now, error="not registered")
        else:
            try:
                health_check = getattr(tool, "health_check", None)
                if callable(health_check):
                    result = health_check()
                    available = bool(result if not isinstance(result, dict) else result.get("available", True))
                    metadata = result if isinstance(result, dict) else {}
                else:
                    available = True
                    metadata = {"mode": "assumed_available"}
                health = ToolHealth(name=name, available=available, checked_at=now, metadata=metadata)
            except Exception as exc:
                health = ToolHealth(name=name, available=False, checked_at=now, error=str(exc))
        self._health[name] = health
        return health

    def list_health(self, *, force: bool = False) -> list[ToolHealth]:
        return [self.check(name, force=force) for name in sorted(self._tools)]


_tool_health_registry = ToolHealthRegistry()


def get_tool_health_registry() -> ToolHealthRegistry:
    return _tool_health_registry
