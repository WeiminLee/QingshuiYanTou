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
