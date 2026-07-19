from unittest.mock import AsyncMock

import pytest

import app.reasoning.langchain_agent.memory.tool as tool_mod


@pytest.mark.asyncio
async def test_tool_passes_preference_args(monkeypatch):
    captured = {}

    class _Mgr:
        async def handle_tool_call(self, name, args):
            captured["name"] = name
            captured["args"] = args
            return "记忆已add。"

    monkeypatch.setattr(tool_mod, "_memory_manager", _Mgr())
    # 直接调用底层协程（绕过 langchain tool wrapper）
    result = await tool_mod.manage_memory.ainvoke({
        "action": "add", "target": "preference",
        "content": "", "subject": "光模块", "stance": "看好",
        "subject_type": "sector", "reason": "AI算力",
    })
    assert "已" in result
    assert captured["args"]["subject"] == "光模块"
    assert captured["args"]["stance"] == "看好"


@pytest.mark.asyncio
async def test_tool_uninitialized(monkeypatch):
    monkeypatch.setattr(tool_mod, "_memory_manager", None)
    result = await tool_mod.manage_memory.ainvoke({
        "action": "add", "target": "notes", "content": "x",
    })
    assert "未初始化" in result
