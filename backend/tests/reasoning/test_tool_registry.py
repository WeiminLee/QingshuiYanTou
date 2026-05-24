"""Tool health registry tests."""
from __future__ import annotations


class HealthyTool:
    name = "healthy_tool"
    description = "research helper"

    def health_check(self):
        return {"available": True, "source": "test"}


class FailingTool:
    name = "failing_tool"
    description = "research helper"

    def health_check(self):
        raise RuntimeError("down")


def test_tool_health_registry_records_available_tool():
    from app.reasoning.tools.registry import ToolHealthRegistry

    registry = ToolHealthRegistry(ttl_seconds=60)
    registry.register(HealthyTool())
    health = registry.check("healthy_tool")

    assert health.available is True
    assert health.metadata["source"] == "test"


def test_tool_health_registry_records_failure():
    from app.reasoning.tools.registry import ToolHealthRegistry

    registry = ToolHealthRegistry(ttl_seconds=60)
    registry.register(FailingTool())
    health = registry.check("failing_tool")

    assert health.available is False
    assert "down" in health.error

