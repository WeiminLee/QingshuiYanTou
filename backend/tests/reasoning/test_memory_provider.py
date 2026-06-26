from unittest.mock import AsyncMock, MagicMock

import pytest

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
