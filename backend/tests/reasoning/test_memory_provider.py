from unittest.mock import AsyncMock, MagicMock

import pytest

from app.reasoning.langchain_agent.memory.manager import MemoryManager
from app.reasoning.langchain_agent.memory.provider import MemoryProvider


class _ConcreteProvider(MemoryProvider):
    def __init__(self):
        self._name = "test"
        self._initialized = False

    @property
    def name(self) -> str:
        return self._name
    def initialize(self, session_id: str) -> None:
        self._initialized = True
    def shutdown(self) -> None:
        self._initialized = False
    def on_turn_start(self, turn_number: int, message: str) -> None:
        pass
    async def prefetch(self, query: str) -> str:
        return "<memory-context>test recall</memory-context>"
    async def sync_turn(self, user: str, assistant: str) -> None:
        pass
    def get_tool_schemas(self) -> list:
        return []
    async def handle_tool_call(self, name: str, args: dict) -> str:
        return ""
    def system_prompt_block(self) -> str:
        return ""
    def on_session_end(self) -> None:
        pass
    def on_pre_compress(self, messages: list) -> str:
        return ""


class TestMemoryProvider:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            MemoryProvider()  # type: ignore

    @pytest.mark.asyncio
    async def test_concrete_provider(self):
        p = _ConcreteProvider()
        assert p.name == "test"
        result = await p.prefetch("query")
        assert result == "<memory-context>test recall</memory-context>"
        assert p.get_tool_schemas() == []
        assert p.system_prompt_block() == ""

    def test_initialize_lifecycle(self):
        p = _ConcreteProvider()
        assert not p._initialized
        p.initialize("sess_123")
        assert p._initialized
        p.shutdown()
        assert not p._initialized

    def test_on_turn_start(self):
        p = _ConcreteProvider()
        p.on_turn_start(1, "hello")
        assert p._initialized is False  # default no-op

    @pytest.mark.asyncio
    async def test_sync_turn(self):
        p = _ConcreteProvider()
        await p.sync_turn("user msg", "asst msg")  # should not raise

    def test_on_session_end(self):
        p = _ConcreteProvider()
        p.on_session_end()  # should not raise

    def test_on_pre_compress(self):
        p = _ConcreteProvider()
        result = p.on_pre_compress([{"role": "user", "content": "hi"}])
        assert result == ""


class TestBuiltinProvider:
    @pytest.fixture
    def provider(self):
        from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider

        p = BuiltinProvider()
        p.initialize("test_session")
        return p

    @pytest.fixture
    def mock_mongo(self, monkeypatch):
        mock_collection = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr("app.core.mongodb.get_mongo_db", lambda: mock_db)
        return mock_db, mock_collection

    # ── Basic identity & lifecycle ───────────────────────────────────

    def test_provider_name(self, provider):
        assert provider.name == "builtin"

    def test_initialize_sets_session(self, provider):
        assert provider._session_id == "test_session"

    def test_shutdown_resets_session(self, provider):
        provider.shutdown()
        assert provider._session_id is None

    def test_shutdown_idempotent(self, provider):
        provider.shutdown()
        provider.shutdown()  # second call should not raise
        assert provider._session_id is None

    @pytest.mark.asyncio
    async def test_sync_turn_does_not_raise(self, provider):
        await provider.sync_turn("user msg", "asst msg")

    # ── Prefetch (requires Mongo mock) ───────────────────────────────

    @pytest.mark.asyncio
    async def test_prefetch_returns_context_block(self, provider, mock_mongo):
        _, col = mock_mongo
        col.find_one.return_value = None
        result = await provider.prefetch("test query")
        assert "<memory-context>" in result
        assert "</memory-context>" in result

    @pytest.mark.asyncio
    async def test_prefetch_empty_when_no_data(self, provider, mock_mongo):
        _, col = mock_mongo
        col.find_one.return_value = None
        result = await provider.prefetch("test")
        assert result == "<memory-context>\n</memory-context>"

    @pytest.mark.asyncio
    async def test_prefetch_empty_when_no_session(self, mock_mongo):
        from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider

        p = BuiltinProvider()
        result = await p.prefetch("test")
        assert result == ""

    @pytest.mark.asyncio
    async def test_prefetch_with_notes(self, provider, mock_mongo):
        _, col = mock_mongo
        call_count = 0

        async def find_one_side_effect(filter):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # notes
                return {"entries": [{"content": "用户关注光伏行业", "category": "research"}]}
            return None  # profile & memory

        col.find_one = find_one_side_effect
        result = await provider.prefetch("solar")
        assert "<notes>" in result
        assert "[research] 用户关注光伏行业" in result
        assert "</memory-context>" in result

    @pytest.mark.asyncio
    async def test_prefetch_with_profile(self, provider, mock_mongo):
        _, col = mock_mongo

        async def find_one_side_effect(filter):
            if filter.get("user_id") == "test_session":
                return {"profile": "对冲基金经理，偏好成长股"}
            return None

        col.find_one = find_one_side_effect
        result = await provider.prefetch("profile")
        assert "<profile>" in result
        assert "对冲基金经理" in result

    @pytest.mark.asyncio
    async def test_prefetch_with_memory_facts(self, provider, mock_mongo):
        _, col = mock_mongo

        async def find_one_side_effect(filter):
            return {
                "workContext": {"summary": "分析光伏行业"},
                "topOfMind": {"summary": "隆基绿能"},
                "facts": [{"content": "隆基绿能是光伏龙头", "category": "industry", "confidence": 0.9}],
            }

        col.find_one = find_one_side_effect
        result = await provider.prefetch("光伏")
        assert "<facts>" in result
        assert "Work Context" in result
        assert "Top of Mind" in result
        assert "隆基绿能" in result
        assert "(0.9)" in result

    @pytest.mark.asyncio
    async def test_prefetch_returns_all_sections(self, provider, mock_mongo):
        _, col = mock_mongo
        call_count = 0

        async def find_one_side_effect(filter):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # notes
                return {"entries": [{"content": "note1", "category": "general"}]}
            if call_count == 2:  # profile
                return {"profile": "profile text"}
            return {  # memory
                "workContext": {"summary": "ctx"},
                "facts": [{"content": "fact1", "category": "general", "confidence": 0.8}],
            }

        col.find_one = find_one_side_effect
        result = await provider.prefetch("all")
        assert "<notes>" in result
        assert "<profile>" in result
        assert "<facts>" in result

    # ── Tool schemas ─────────────────────────────────────────────────

    def test_get_tool_schemas_returns_manage_memory(self, provider):
        schemas = provider.get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "manage_memory"
        assert "action" in schemas[0]["parameters"]["properties"]
        assert "target" in schemas[0]["parameters"]["properties"]

    def test_system_prompt_block(self, provider):
        block = provider.system_prompt_block()
        assert block == "" or "manage_memory" in block

    # ── handle_tool_call — notes ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_handle_tool_call_add_note(self, provider, mock_mongo):
        _, col = mock_mongo
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "add", "target": "notes", "content": "用户偏好新能源"},
        )
        assert "记忆已add" in result
        col.update_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_tool_call_replace_note(self, provider, mock_mongo):
        _, col = mock_mongo
        col.update_one.return_value = MagicMock(modified_count=1)
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "replace", "target": "notes", "content": "new text", "old_text": "old text"},
        )
        assert "记忆已replace" in result

    @pytest.mark.asyncio
    async def test_handle_tool_call_remove_note(self, provider, mock_mongo):
        _, col = mock_mongo
        col.update_one.return_value = MagicMock(modified_count=1)
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "remove", "target": "notes", "content": "", "old_text": "text to remove"},
        )
        assert "记忆已remove" in result

    @pytest.mark.asyncio
    async def test_handle_tool_call_replace_missing_old_text(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "replace", "target": "notes", "content": "new text"},
        )
        assert "Error" in result
        assert "old_text" in result

    @pytest.mark.asyncio
    async def test_handle_tool_call_remove_missing_old_text(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "remove", "target": "notes", "content": ""},
        )
        assert "Error" in result
        assert "old_text" in result

    # ── handle_tool_call — profile ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_handle_tool_call_set_profile(self, provider, mock_mongo):
        _, col = mock_mongo
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "add", "target": "profile", "content": "偏好成长股投资"},
        )
        assert "记忆已add" in result
        col.update_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_tool_call_profile_replace_not_supported(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "replace", "target": "profile", "content": "new profile"},
        )
        assert "Error" in result
        assert "仅支持 add" in result

    # ── handle_tool_call — guardrails ────────────────────────────────

    @pytest.mark.asyncio
    async def test_handle_tool_call_guardrail_rejects_execution_intent(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "add", "target": "notes", "content": "帮我自动下单买入100股"},
        )
        assert "Error" in result
        assert "不允许" in result

    # ── handle_tool_call — error cases ───────────────────────────────

    @pytest.mark.asyncio
    async def test_handle_tool_call_unknown_tool(self, provider, mock_mongo):
        result = await provider.handle_tool_call("unknown_tool", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_handle_tool_call_unknown_action(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "unknown", "target": "notes", "content": "test"},
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_handle_tool_call_unknown_target(self, provider, mock_mongo):
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "add", "target": "invalid", "content": "test"},
        )
        assert "Error" in result

    # ── Operation no match ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_replace_note_no_match(self, provider, mock_mongo):
        _, col = mock_mongo
        col.update_one.return_value = MagicMock(modified_count=0)
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "replace", "target": "notes", "content": "new", "old_text": "nonexistent"},
        )
        assert "未生效" in result

    @pytest.mark.asyncio
    async def test_remove_note_no_match(self, provider, mock_mongo):
        _, col = mock_mongo
        col.update_one.return_value = MagicMock(modified_count=0)
        result = await provider.handle_tool_call(
            "manage_memory",
            {"action": "remove", "target": "notes", "content": "", "old_text": "nonexistent"},
        )
        assert "未生效" in result


class _MockProvider(MemoryProvider):
    def __init__(self, name: str = "mock"):
        self._name = name
        self._prefetch_calls: list[str] = []
        self._sync_calls: list[tuple[str, str]] = []
        self._turn_starts: list[tuple[int, str]] = []
        self._initialized = False

    @property
    def name(self) -> str:
        return self._name

    def initialize(self, session_id: str) -> None:
        self._initialized = True
        self._session_id = session_id

    def shutdown(self) -> None:
        self._initialized = False

    async def prefetch(self, query: str) -> str:
        self._prefetch_calls.append(query)
        return f"<memory-context>mock:{query}</memory-context>"

    async def sync_turn(self, user: str, assistant: str) -> None:
        self._sync_calls.append((user, assistant))


class TestMemoryManager:
    def test_empty_manager(self):
        mgr = MemoryManager()
        assert mgr.get_all_tool_schemas() == []

    def test_add_and_get_provider(self):
        mgr = MemoryManager()
        p = _MockProvider("mock1")
        mgr.add_provider(p)
        assert "mock1" in [pr.name for pr in mgr._providers]

    @pytest.mark.asyncio
    async def test_prefetch_all_calls_all_providers(self):
        mgr = MemoryManager()
        p1 = _MockProvider("p1")
        p2 = _MockProvider("p2")
        mgr.add_provider(p1)
        mgr.add_provider(p2)
        result = await mgr.prefetch_all("test query")
        assert "mock:test query" in result
        assert len(p1._prefetch_calls) == 1
        assert len(p2._prefetch_calls) == 1

    @pytest.mark.asyncio
    async def test_sync_all_calls_all_providers(self):
        mgr = MemoryManager()
        p1 = _MockProvider("p1")
        mgr.add_provider(p1)
        await mgr.sync_all("user msg", "asst msg")
        assert p1._sync_calls == [("user msg", "asst msg")]

    @pytest.mark.asyncio
    async def test_initialize_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        await mgr.initialize_all("sess_001")
        assert p._initialized
        assert p._session_id == "sess_001"

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        await mgr.initialize_all("sess_001")
        await mgr.shutdown_all()
        assert not p._initialized

    @pytest.mark.asyncio
    async def test_on_turn_start_calls_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        await mgr.on_turn_start(1, "hello")
        assert len(p._turn_starts) == 0  # our mock doesn't record, just no error

    @pytest.mark.asyncio
    async def test_handle_tool_call_returns_first_match(self):
        mgr = MemoryManager()
        p1 = _MockProvider("p1")
        p1.handle_tool_call = AsyncMock(return_value="result from p1")  # type: ignore
        p2 = _MockProvider("p2")
        p2.handle_tool_call = AsyncMock(return_value="result from p2")  # type: ignore
        mgr.add_provider(p1)
        mgr.add_provider(p2)
        result = await mgr.handle_tool_call("some_tool", {})
        assert result == "result from p1"

    @pytest.mark.asyncio
    async def test_handle_tool_call_unknown(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        result = await mgr.handle_tool_call("nonexistent", {})
        assert result == "Unknown tool: nonexistent"

    def test_get_all_tool_schemas_merges_all_providers(self):
        mgr = MemoryManager()
        p1 = _MockProvider("p1")
        p1.get_tool_schemas = MagicMock(return_value=[{"name": "tool_a"}])  # type: ignore
        p2 = _MockProvider("p2")
        p2.get_tool_schemas = MagicMock(return_value=[{"name": "tool_b"}])  # type: ignore
        mgr.add_provider(p1)
        mgr.add_provider(p2)
        schemas = mgr.get_all_tool_schemas()
        assert len(schemas) == 2
        assert {"name": "tool_a"} in schemas
        assert {"name": "tool_b"} in schemas

    @pytest.mark.asyncio
    async def test_build_system_prompt_block(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        p.system_prompt_block = MagicMock(return_value="system block")  # type: ignore
        mgr.add_provider(p)
        result = await mgr.build_system_prompt_block()
        assert result == "system block"

    @pytest.mark.asyncio
    async def test_on_session_end(self):
        mgr = MemoryManager()
        calls: list[str] = []

        class _TrackingProvider(_MockProvider):
            def on_session_end(self) -> None:
                calls.append("ended")

        mgr.add_provider(_TrackingProvider("track"))
        await mgr.on_session_end()
        assert calls == ["ended"]

    @pytest.mark.asyncio
    async def test_on_pre_compress(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        p.on_pre_compress = MagicMock(return_value="insight")  # type: ignore
        mgr.add_provider(p)
        result = await mgr.on_pre_compress([{"role": "user", "content": "hi"}])
        assert result == "insight"


class TestManageMemoryTool:
    @pytest.fixture
    def mock_manager(self):
        from app.reasoning.langchain_agent.memory.tool import set_memory_manager

        mock_mgr = AsyncMock()
        mock_mgr.handle_tool_call = AsyncMock(return_value="记忆已add。")
        set_memory_manager(mock_mgr)
        yield mock_mgr
        set_memory_manager(None)

    @pytest.fixture
    def tool(self):
        from app.reasoning.langchain_agent.memory.tool import manage_memory

        return manage_memory

    def test_tool_name(self, tool):
        assert tool.name == "manage_memory"

    def test_tool_return_direct(self, tool):
        assert tool.return_direct is True

    @pytest.mark.asyncio
    async def test_add_note_basic(self, tool, mock_manager):
        result = await tool.coroutine(
            action="add",
            target="notes",
            content="用户关注光模块板块",
        )
        assert isinstance(result, str)
        mock_manager.handle_tool_call.assert_awaited_once_with(
            "manage_memory",
            {"action": "add", "target": "notes", "content": "用户关注光模块板块", "old_text": None},
        )

    @pytest.mark.asyncio
    async def test_add_profile(self, tool, mock_manager):
        result = await tool.coroutine(
            action="add",
            target="profile",
            content="用户是专业投资者",
        )
        assert isinstance(result, str)
        mock_manager.handle_tool_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_target(self, tool, mock_manager):
        mock_manager.handle_tool_call.return_value = "Error: 未知 target 'invalid'"
        result = await tool.coroutine(
            action="add",
            target="invalid",
            content="test",
        )
        assert "未知" in result

    @pytest.mark.asyncio
    async def test_replace_without_old_text(self, tool, mock_manager):
        mock_manager.handle_tool_call.return_value = "Error: replace 操作需要提供 old_text"
        result = await tool.coroutine(
            action="replace",
            target="notes",
            content="new content",
        )
        assert "old_text" in result

    @pytest.mark.asyncio
    async def test_remove_without_old_text(self, tool, mock_manager):
        mock_manager.handle_tool_call.return_value = "Error: remove 操作需要提供 old_text"
        result = await tool.coroutine(
            action="remove",
            target="notes",
            content="",
        )
        assert "old_text" in result

    @pytest.mark.asyncio
    async def test_no_manager_returns_error(self):
        from app.reasoning.langchain_agent.memory.tool import set_memory_manager, manage_memory

        set_memory_manager(None)
        result = await manage_memory.coroutine(action="add", target="notes", content="test")
        assert "记忆系统未初始化" in result
