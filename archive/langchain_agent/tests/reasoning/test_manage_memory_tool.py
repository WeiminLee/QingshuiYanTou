
import pytest

import app.reasoning.langchain_agent.memory.tool as tool_mod


class _Mgr:
    def __init__(self, label):
        self.label = label
        self.calls = []

    async def handle_tool_call(self, name, args):
        self.calls.append((name, args))
        return f"{self.label}:记忆已add。"


@pytest.mark.asyncio
async def test_tool_passes_preference_args(monkeypatch):
    captured = {}

    class _CompatMgr:
        async def handle_tool_call(self, name, args):
            captured["name"] = name
            captured["args"] = args
            return "记忆已add。"

    monkeypatch.setattr(tool_mod, "_memory_manager", _CompatMgr())
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


@pytest.mark.asyncio
async def test_create_manage_memory_tool_binds_manager_per_run():
    mgr_a = _Mgr("A")
    mgr_b = _Mgr("B")
    tool_a = tool_mod.create_manage_memory_tool(mgr_a)
    tool_b = tool_mod.create_manage_memory_tool(mgr_b)

    assert tool_a.return_direct is False
    assert tool_b.return_direct is False

    result_a = await tool_a.ainvoke({"action": "add", "target": "notes", "content": "a"})
    result_b = await tool_b.ainvoke({"action": "add", "target": "notes", "content": "b"})

    assert result_a.startswith("A:")
    assert result_b.startswith("B:")
    assert mgr_a.calls[0][1]["content"] == "a"
    assert mgr_b.calls[0][1]["content"] == "b"
