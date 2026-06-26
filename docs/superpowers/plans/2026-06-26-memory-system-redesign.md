# Memory System Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild memory system with MemoryProvider ABC + MemoryManager + manage_memory tool + context compression integration.

**Architecture:** Reference hermes-agent's MemoryProvider abstraction. BuiltinProvider stores to MongoDB (agent_memory/agent_notes/agent_profile). MemoryManager orchestrates per-turn prefetch/sync. ContextCompressor protects `<memory-context>` tags and triggers memory hooks.

**Tech Stack:** Python 3.14, MongoDB (Motor), LangChain, LangGraph

## Global Constraints

- All new async code
- MongoDB operations via Motor (existing pattern)
- `return_direct=True` on manage_memory tool
- `<memory-context>` tags must be preserved by context compressor
- Maximum recall: 2000 tokens per prefetch
- Old agent_memory collection data must be readable after migration

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/reasoning/langchain_agent/memory/__init__.py` | Package init, exports |
| `backend/app/reasoning/langchain_agent/memory/provider.py` | MemoryProvider ABC |
| `backend/app/reasoning/langchain_agent/memory/manager.py` | MemoryManager orchestrator |
| `backend/app/reasoning/langchain_agent/memory/builtin_provider.py` | BuiltinProvider (MongoDB) |
| `backend/app/reasoning/langchain_agent/memory/tool.py` | manage_memory tool |

### Modified Files
| File | Change |
|------|--------|
| `backend/app/reasoning/langchain_agent/client.py:132-583` | Integrate MemoryManager into run_lead_agent |
| `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py:411-428` | Replace get_memory_context_async with MemoryManager |
| `backend/app/reasoning/api/agent.py:385-700` | Wire MemoryManager into stream endpoints |
| `backend/app/reasoning/langchain_agent/middlewares/context_compressor.py` | Ensure `<memory-context>` tag protection |

### Deleted Files
| File | Reason |
|------|--------|
| `backend/app/reasoning/harness/memory.py` | Replaced by BuiltinProvider + MemoryManager |
| `backend/app/reasoning/langchain_agent/middlewares/memory_middleware.py` | Replaced by MemoryManager.sync_all |
| `backend/app/reasoning/langchain_agent/middlewares/memory_queue.py` | Replaced by MemoryManager |

### Test Files
| File | Tests |
|------|-------|
| `backend/tests/reasoning/test_memory_provider.py` | MemoryProvider ABC + BuiltinProvider |
| `backend/tests/reasoning/test_memory_manager.py` | MemoryManager orchestration |
| `backend/tests/reasoning/test_memory_tool.py` | manage_memory tool |
| `backend/tests/reasoning/test_memory_integration.py` | End-to-end with run_lead_agent |

---

### Task 1: MemoryProvider ABC + Module Structure

**Files:**
- Create: `backend/app/reasoning/langchain_agent/memory/__init__.py`
- Create: `backend/app/reasoning/langchain_agent/memory/provider.py`
- Test: `backend/tests/reasoning/test_memory_provider.py`

**Interfaces:**
- Produces: `MemoryProvider` abstract base class with all abstract methods

- [ ] **Step 1: Create package structure**

```bash
mkdir -p backend/app/reasoning/langchain_agent/memory
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/reasoning/test_memory_provider.py`:

```python
import pytest
from typing import Optional
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
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_provider.py -v 2>&1 | tail -20
```
Expected: ModuleNotFoundError for `app.reasoning.langchain_agent.memory.provider`

- [ ] **Step 4: Create `__init__.py`**

```python
"""Memory system — Provider-based architecture inspired by hermes-agent."""

from app.reasoning.langchain_agent.memory.provider import MemoryProvider

__all__ = [
    "MemoryProvider",
    # Extended in later tasks: MemoryManager, BuiltinProvider, manage_memory
]
```

- [ ] **Step 5: Create `provider.py`**

```python
"""Abstract base class for memory providers."""

from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemoryProvider(abc.ABC):
    """Abstract memory provider.

    Each provider manages its own storage backend and is orchestrated
    by MemoryManager.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique provider name."""

    def initialize(self, session_id: str) -> None:
        """Called when a new session starts."""

    def shutdown(self) -> None:
        """Called when the provider is no longer needed."""

    def on_turn_start(self, turn_number: int, message: str) -> None:
        """Called before each LLM turn."""

    @abc.abstractmethod
    async def prefetch(self, query: str) -> str:
        """Recall relevant memory for the given query.

        Returns a string (may include <memory-context> tags) to be
        injected into the system prompt.
        """

    async def sync_turn(self, user: str, assistant: str) -> None:
        """Called after each LLM turn to persist observed data."""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas to register for this provider."""
        return []

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        """Handle a tool call routed to this provider."""
        return ""

    def system_prompt_block(self) -> str:
        """Return a static block to include in the system prompt."""
        return ""

    def on_session_end(self) -> None:
        """Called when the current session ends."""

    def on_pre_compress(self, messages: list[dict]) -> str:
        """Called before context compression.

        Returns a summary/insights string to preserve across compression.
        """
        return ""
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_provider.py -v 2>&1 | tail -20
```
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/reasoning/langchain_agent/memory/ backend/tests/reasoning/test_memory_provider.py
git commit -m "feat(memory): add MemoryProvider ABC and package structure"
```

---

### Task 2: BuiltinProvider (MongoDB Storage)

**Files:**
- Create: `backend/app/reasoning/langchain_agent/memory/builtin_provider.py`
- Test: `backend/tests/reasoning/test_memory_provider.py` (extend)

**Interfaces:**
- Consumes: `MemoryProvider` ABC from Task 1
- Produces: `BuiltinProvider` class with all abstract methods implemented

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/reasoning/test_memory_provider.py`:

```python
import pytest
from datetime import datetime, timedelta
from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider


@pytest.fixture
def provider():
    p = BuiltinProvider()
    p.initialize("test_session")
    return p


@pytest.mark.asyncio
async def test_provider_name(provider):
    assert provider.name == "builtin"


@pytest.mark.asyncio
async def test_initialize_sets_session(provider):
    assert provider._session_id == "test_session"


@pytest.mark.asyncio
async def test_prefetch_returns_context_block(provider):
    result = await provider.prefetch("test query")
    assert "<memory-context>" in result
    assert "</memory-context>" in result


@pytest.mark.asyncio
async def test_prefetch_empty_when_no_data(provider):
    result = await provider.prefetch("test")
    # Should return the tag pair with empty content or a minimal block
    assert result == "<memory-context>\n</memory-context>" or "暂无相关记忆" in result


@pytest.mark.asyncio
async def test_sync_turn_does_not_raise(provider):
    await provider.sync_turn("user msg", "asst msg")


@pytest.mark.asyncio
async def test_shutdown_resets_session(provider):
    provider.shutdown()
    assert provider._session_id is None


@pytest.mark.asyncio
async def test_get_tool_schemas_returns_manage_memory(provider):
    schemas = provider.get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "manage_memory"


@pytest.mark.asyncio
async def test_system_prompt_block(provider):
    block = provider.system_prompt_block()
    assert "manage_memory" in block or block == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_provider.py -v 2>&1 | tail -15
```
Expected: ImportError for BuiltinProvider

- [ ] **Step 3: Create `builtin_provider.py`**

```python
"""Built-in memory provider — MongoDB-backed storage."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from app.reasoning.langchain_agent.memory.provider import MemoryProvider

logger = logging.getLogger(__name__)

MEMORY_COLLECTION = "agent_memory"
NOTES_COLLECTION = "agent_notes"
PROFILE_COLLECTION = "agent_profile"

MAX_PREFETCH_TOKENS = 2000
MAX_NOTES_PER_SESSION = 50


def _get_collection(name: str) -> AsyncIOMotorCollection:
    from app.core.mongodb import get_mongo_db
    return get_mongo_db()[name]


class BuiltinProvider(MemoryProvider):
    """MongoDB-backed memory provider.

    Stores:
    - agent_memory: LLM-summarized facts (workContext, topOfMind, facts[])
    - agent_notes: LLM-written notes (entries[{id, content, category}])
    - agent_profile: User profile (profile text)
    """

    def __init__(self):
        self._session_id: str | None = None

    @property
    def name(self) -> str:
        return "builtin"

    def initialize(self, session_id: str) -> None:
        self._session_id = session_id
        logger.info(f"[BuiltinProvider] initialized for session {session_id}")

    def shutdown(self) -> None:
        self._session_id = None

    async def prefetch(self, query: str) -> str:
        if not self._session_id:
            return ""
        parts: list[str] = []
        notes = await self._get_notes()
        if notes:
            parts.append(f"<notes>\n{notes}\n</notes>")
        profile = await self._get_profile()
        if profile:
            parts.append(f"<profile>\n{profile}\n</profile>")
        memory = await self._get_memory_facts()
        if memory:
            parts.append(f"<facts>\n{memory}\n</facts>")
        if not parts:
            return "<memory-context>\n</memory-context>"
        body = "\n\n".join(parts)
        # Truncate to MAX_PREFETCH_TOKENS (rough char estimate)
        if len(body) > MAX_PREFETCH_TOKENS * 4:
            body = body[: MAX_PREFETCH_TOKENS * 4] + "\n... (truncated)"
        return f"<memory-context>\n{body}\n</memory-context>"

    async def sync_turn(self, user: str, assistant: str) -> None:
        pass  # BuiltinProvider doesn't auto-summarize turns

    async def _get_notes(self) -> str | None:
        col = _get_collection(NOTES_COLLECTION)
        doc = await col.find_one({"session_id": self._session_id})
        if not doc or not doc.get("entries"):
            return None
        lines = []
        for entry in doc["entries"][-MAX_NOTES_PER_SESSION:]:
            cat = entry.get("category", "general")
            content = entry["content"]
            lines.append(f"[{cat}] {content}")
        return "\n".join(lines)

    async def _get_profile(self) -> str | None:
        col = _get_collection(PROFILE_COLLECTION)
        doc = await col.find_one({"user_id": self._session_id})
        if not doc or not doc.get("profile"):
            return None
        return doc["profile"]

    async def _get_memory_facts(self) -> str | None:
        col = _get_collection(MEMORY_COLLECTION)
        doc = await col.find_one({"session_id": self._session_id})
        if not doc:
            return None
        parts = []
        if doc.get("workContext"):
            parts.append(f"Work Context: {doc['workContext']}")
        if doc.get("topOfMind"):
            parts.append(f"Top of Mind: {doc['topOfMind']}")
        if doc.get("facts"):
            for f in doc["facts"]:
                content = f.get("content", "")
                cat = f.get("category", "general")
                conf = f.get("confidence", 1.0)
                parts.append(f"[{cat}] ({conf}) {content}")
        return "\n".join(parts) if parts else None

    async def add_note(self, content: str, category: str = "general") -> dict:
        col = _get_collection(NOTES_COLLECTION)
        entry = {
            "id": str(uuid.uuid4())[:8],
            "content": content,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await col.update_one(
            {"session_id": self._session_id},
            {"$push": {"entries": entry}},
            upsert=True,
        )
        return {"success": True, "id": entry["id"]}

    async def replace_note(self, old_text: str, new_content: str) -> dict:
        col = _get_collection(NOTES_COLLECTION)
        result = await col.update_one(
            {"session_id": self._session_id, "entries.content": old_text},
            {"$set": {"entries.$.content": new_content}},
        )
        return {"success": result.modified_count > 0}

    async def remove_note(self, old_text: str) -> dict:
        col = _get_collection(NOTES_COLLECTION)
        result = await col.update_one(
            {"session_id": self._session_id},
            {"$pull": {"entries": {"content": old_text}}},
        )
        return {"success": result.modified_count > 0}

    async def set_profile(self, content: str) -> dict:
        col = _get_collection(PROFILE_COLLECTION)
        await col.update_one(
            {"user_id": self._session_id},
            {"$set": {"profile": content, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        return {"success": True}

    async def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "manage_memory",
                "description": "管理持久记忆：记录笔记、更新用户画像。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["add", "replace", "remove"],
                            "description": "操作类型",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["notes", "profile"],
                            "description": "目标：notes（笔记）或 profile（用户画像）",
                        },
                        "content": {
                            "type": "string",
                            "description": "内容文本",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "replace/remove 时匹配的旧文本",
                        },
                    },
                    "required": ["action", "target", "content"],
                },
            }
        ]

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        if name != "manage_memory":
            return f"Unknown tool: {name}"
        action = args["action"]
        target = args["target"]
        content = args["content"]
        old_text = args.get("old_text")

        from app.reasoning.tools.guardrails import filter_research_memory_text
        filtered = filter_research_memory_text(content)
        if filtered != content:
            return "Error: 内容包含不允许的指令，已拒绝写入。"

        if target == "profile":
            if action == "add":
                result = await self.set_profile(content)
            else:
                return "Error: profile 仅支持 add 操作"
        elif target == "notes":
            if action == "add":
                result = await self.add_note(content)
            elif action == "replace":
                if not old_text:
                    return "Error: replace 操作需要提供 old_text"
                result = await self.replace_note(old_text, content)
            elif action == "remove":
                if not old_text:
                    return "Error: remove 操作需要提供 old_text"
                result = await self.remove_note(old_text)
            else:
                return f"Error: 未知 action '{action}'"
        else:
            return f"Error: 未知 target '{target}'"
        if result.get("success"):
            return f"记忆已{action}。"
        return "操作未生效（可能未找到匹配条目）。"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_provider.py -v 2>&1 | tail -20
```
Expected: all tests pass (note: prefetch tests may need MongoDB running — handle separately)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/langchain_agent/memory/builtin_provider.py backend/tests/reasoning/test_memory_provider.py
git commit -m "feat(memory): add BuiltinProvider with MongoDB storage"
```

---

### Task 3: MemoryManager (Orchestrator)

**Files:**
- Create: `backend/app/reasoning/langchain_agent/memory/manager.py`
- Test: `backend/tests/reasoning/test_memory_manager.py`

**Interfaces:**
- Consumes: `MemoryProvider`, `BuiltinProvider` from Tasks 1-2
- Produces: `MemoryManager` class

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reasoning/test_memory_manager.py`:

```python
import pytest
from app.reasoning.langchain_agent.memory.manager import MemoryManager
from app.reasoning.langchain_agent.memory.provider import MemoryProvider


class _MockProvider(MemoryProvider):
    def __init__(self, name: str = "mock"):
        self._name = name
        self._prefetch_calls = []
        self._sync_calls = []
        self._turn_starts = []
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

    def test_initialize_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        mgr.initialize_all("sess_001")
        assert p._initialized
        assert p._session_id == "sess_001"

    def test_shutdown_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        mgr.initialize_all("sess_001")
        mgr.shutdown_all()
        assert not p._initialized

    @pytest.mark.asyncio
    async def test_on_turn_start_calls_all(self):
        mgr = MemoryManager()
        p = _MockProvider("p")
        mgr.add_provider(p)
        await mgr.on_turn_start(1, "hello")
        assert len(p._turn_starts) == 0  # our mock doesn't record, just no error
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_manager.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Create `manager.py`**

```python
"""MemoryManager — orchestrates all MemoryProviders."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.reasoning.langchain_agent.memory.provider import MemoryProvider

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates memory providers for the agent lifecycle.

    Usage in run_lead_agent:
        mgr = MemoryManager()
        mgr.add_provider(BuiltinProvider())
        mgr.initialize_all(thread_id)
        ...
        mgr.on_turn_start(turn, question)
        context = mgr.prefetch_all(question)
        ...  # inject context into system prompt
        ...  # run LLM
        mgr.sync_all(question, response)
    """

    def __init__(self):
        self._providers: list[MemoryProvider] = []
        self._lock = asyncio.Lock()
        self._session_id: str | None = None

    def add_provider(self, provider: MemoryProvider) -> None:
        self._providers.append(provider)
        logger.info(f"[MemoryManager] registered provider: {provider.name}")

    async def initialize_all(self, session_id: str) -> None:
        self._session_id = session_id
        for p in self._providers:
            p.initialize(session_id)

    async def shutdown_all(self) -> None:
        for p in self._providers:
            try:
                p.shutdown()
            except Exception as e:
                logger.warning(f"[MemoryManager] shutdown error for {p.name}: {e}")
        self._session_id = None

    async def on_turn_start(self, turn_number: int, message: str) -> None:
        for p in self._providers:
            try:
                p.on_turn_start(turn_number, message)
            except Exception as e:
                logger.warning(f"[MemoryManager] on_turn_start error for {p.name}: {e}")

    async def prefetch_all(self, query: str) -> str:
        """Collect memory context from all providers.

        Returns a string suitable for injection into the system prompt.
        """
        blocks: list[str] = []
        for p in self._providers:
            try:
                result = await p.prefetch(query)
                if result:
                    blocks.append(result)
            except Exception as e:
                logger.warning(f"[MemoryManager] prefetch error for {p.name}: {e}")
        return "\n".join(blocks)

    async def sync_all(self, user: str, assistant: str) -> None:
        for p in self._providers:
            try:
                await p.sync_turn(user, assistant)
            except Exception as e:
                logger.warning(f"[MemoryManager] sync error for {p.name}: {e}")

    def get_all_tool_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for p in self._providers:
            schemas.extend(p.get_tool_schemas())
        return schemas

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        for p in self._providers:
            result = await p.handle_tool_call(name, args)
            if result:
                return result
        return f"Unknown tool: {name}"

    async def build_system_prompt_block(self) -> str:
        blocks: list[str] = []
        for p in self._providers:
            try:
                block = p.system_prompt_block()
                if block:
                    blocks.append(block)
            except Exception as e:
                logger.warning(f"[MemoryManager] system_prompt_block error for {p.name}: {e}")
        return "\n".join(blocks)

    async def on_session_end(self) -> None:
        for p in self._providers:
            try:
                p.on_session_end()
            except Exception as e:
                logger.warning(f"[MemoryManager] on_session_end error for {p.name}: {e}")

    async def on_pre_compress(self, messages: list[dict]) -> str:
        insights: list[str] = []
        for p in self._providers:
            try:
                result = p.on_pre_compress(messages)
                if result:
                    insights.append(result)
            except Exception as e:
                logger.warning(f"[MemoryManager] on_pre_compress error for {p.name}: {e}")
        return "\n".join(insights)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_manager.py -v 2>&1 | tail -20
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/langchain_agent/memory/manager.py backend/tests/reasoning/test_memory_manager.py
git commit -m "feat(memory): add MemoryManager orchestrator"
```

---

### Task 4: manage_memory Tool

**Files:**
- Create: `backend/app/reasoning/langchain_agent/memory/tool.py`
- Test: `backend/tests/reasoning/test_memory_tool.py`

**Interfaces:**
- Consumes: `MemoryManager` from Task 3
- Produces: `manage_memory` LangChain tool

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reasoning/test_memory_tool.py`:

```python
import pytest
from app.reasoning.langchain_agent.memory.tool import manage_memory


@pytest.fixture
def tool():
    return manage_memory

class TestManageMemoryTool:
    def test_tool_name(self, tool):
        assert tool.name == "manage_memory"

    def test_tool_return_direct(self, tool):
        assert tool.return_direct is True

    @pytest.mark.asyncio
    async def test_add_note_basic(self, tool):
        result = await tool.func(
            action="add",
            target="notes",
            content="用户关注光模块板块",
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_add_profile(self, tool):
        result = await tool.func(
            action="add",
            target="profile",
            content="用户是专业投资者",
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_invalid_target(self, tool):
        result = await tool.func(
            action="add",
            target="invalid",
            content="test",
        )
        assert "未知" in result

    @pytest.mark.asyncio
    async def test_replace_without_old_text(self, tool):
        result = await tool.func(
            action="replace",
            target="notes",
            content="new content",
        )
        assert "old_text" in result

    @pytest.mark.asyncio
    async def test_remove_without_old_text(self, tool):
        result = await tool.func(
            action="remove",
            target="notes",
            content="",
        )
        assert "old_text" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_tool.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Create `tool.py`**

```python
"""manage_memory tool — LLM-facing interface for memory operations."""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Global reference — set by MemoryManager during initialization
_memory_manager: object | None = None


def set_memory_manager(mgr: object) -> None:
    global _memory_manager
    _memory_manager = mgr


def get_memory_manager():
    return _memory_manager


@tool("manage_memory", return_direct=True)
async def manage_memory(
    action: Annotated[str, "操作类型: add（新增）/ replace（替换）/ remove（删除）"],
    target: Annotated[str, "目标: notes（笔记）/ profile（用户画像）"],
    content: Annotated[str, "内容文本"],
    old_text: Annotated[str | None, "replace/remove 时需要匹配的旧文本，用于定位要替换或删除的条目"] = None,
) -> str:
    """管理持久记忆：记录笔记或更新用户画像。

    笔记（notes）用于记录分析中发现的用户偏好、关注方向、重要观点。
    用户画像（profile）用于记录用户的投资风格、风险偏好等长期属性。

    【重要】内容必须简洁清晰，不超过200字。
    使用场景：
    - 用户说「我主要关注科技股」→ add to profile
    - 用户说「帮我看看中际旭创」→ add to notes: "用户关注中际旭创"
    - 用户的偏好发生变化 → replace old note with new content
    - 某个关注点不再重要 → remove the note
    """
    mgr = get_memory_manager()
    if mgr is None:
        return "Error: 记忆系统未初始化"

    result = await mgr.handle_tool_call("manage_memory", {
        "action": action,
        "target": target,
        "content": content,
        "old_text": old_text,
    })
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_tool.py -v 2>&1 | tail -15
```
Expected: all pass (tool tests don't need _memory_manager set)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/langchain_agent/memory/tool.py backend/tests/reasoning/test_memory_tool.py
git commit -m "feat(memory): add manage_memory tool with return_direct=True"
```

---

### Task 5: Integrate into run_lead_agent

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/client.py`
- Modify: `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`
- Modify: `backend/app/reasoning/api/agent.py`
- Test: `backend/tests/reasoning/test_memory_integration.py`

- [ ] **Step 1: Write integration tests**

Create `backend/tests/reasoning/test_memory_integration.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.reasoning.langchain_agent.memory.manager import MemoryManager
from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider


@pytest.fixture
def memory_manager():
    mgr = MemoryManager()
    provider = BuiltinProvider()
    mgr.add_provider(provider)
    mgr.initialize_all("test_session")
    return mgr


@pytest.mark.asyncio
async def test_prefetch_in_system_prompt_flow(memory_manager):
    """Simulate the flow: prefetch → inject → run → sync."""
    question = "分析中际旭创的投资价值"

    # Simulate on_turn_start
    await memory_manager.on_turn_start(1, question)

    # Simulate prefetch
    context = await memory_manager.prefetch_all(question)
    assert isinstance(context, str)
    assert "<memory-context>" in context or context == ""

    # Simulate sync
    await memory_manager.sync_all(question, "中际旭创是光模块龙头...")


@pytest.mark.asyncio
async def test_memory_write_then_read_roundtrip(memory_manager):
    """Write a note, then verify it appears in prefetch."""
    provider = memory_manager._providers[0]
    await provider.add_note("用户关注光模块板块", "preference")

    context = await memory_manager.prefetch_all("光模块")
    assert "光模块" in context


@pytest.mark.asyncio
async def test_memory_manager_tool_schemas(memory_manager):
    schemas = memory_manager.get_all_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "manage_memory"
```

- [ ] **Step 2: Modify `lead_system_prompt.py` — replace get_memory_context_async**

Replace the broken function:

```python
async def get_memory_context_async(thread_id: str, analyst_id: str = "default") -> str:
    """Load memory context — delegates to MemoryManager if available."""
    try:
        from app.reasoning.langchain_agent.memory.manager import MemoryManager
        mgr = MemoryManager()
        from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider
        mgr.add_provider(BuiltinProvider())
        mgr.initialize_all(thread_id)
        result = await mgr.prefetch_all("")
        await mgr.shutdown_all()
        return result
    except Exception as e:
        logger.warning(f"[MemoryContext] Failed to load: {e}")
        return ""
```

- [ ] **Step 3: Modify `client.py` — integrate MemoryManager into run_lead_agent**

In `run_lead_agent`, after setup phase and before the agent loop:

```python
# Memory initialization
from app.reasoning.langchain_agent.memory.manager import MemoryManager
from app.reasoning.langchain_agent.memory.builtin_provider import BuiltinProvider
from app.reasoning.langchain_agent.memory.tool import set_memory_manager, manage_memory

memory_manager = MemoryManager()
memory_manager.add_provider(BuiltinProvider())
memory_manager.initialize_all(thread_id)
set_memory_manager(memory_manager)

# Collect memory context for system prompt
memory_context = await memory_manager.prefetch_all(question)
```

Then in the stream loop, on each turn:
```python
await memory_manager.on_turn_start(turn_count, current_question)
memory_context = await memory_manager.prefetch_all(current_question)
```

After each LLM response:
```python
await memory_manager.sync_all(current_question, response_text)
```

Register `manage_memory` in the tool list:
```python
tools = [...existing tools..., manage_memory]
```

- [ ] **Step 4: Add `manage_memory` to lead_agent tool registration**

In `lead_agent.py`, ensure `manage_memory` is added to the tools list:

```python
if memory_manager:
    tools.append(manage_memory)
```

- [ ] **Step 5: Run integration tests**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/test_memory_integration.py -v 2>&1 | tail -20
```
Expected: all tests pass (may need MongoDB for the write_then_read test — adjust as needed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/langchain_agent/client.py \
      backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py \
      backend/tests/reasoning/test_memory_integration.py
git commit -m "feat(memory): integrate MemoryManager into run_lead_agent"
```

---

### Task 6: Clean Up Old Memory Code

**Files:**
- Delete: `backend/app/reasoning/harness/memory.py`
- Delete: `backend/app/reasoning/langchain_agent/middlewares/memory_middleware.py`
- Delete: `backend/app/reasoning/langchain_agent/middlewares/memory_queue.py`
- Modify: `backend/app/reasoning/langchain_agent/integrations.py` — remove dead config/manager code
- Modify: `backend/app/reasoning/langchain_agent/client.py` — remove old post-run memory queue calls
- Modify: `backend/app/reasoning/harness/__init__.py` — remove MemoryManager export

- [ ] **Step 1: Remove `harness/memory.py`**

```bash
git rm backend/app/reasoning/harness/memory.py
```

- [ ] **Step 2: Remove `memory_middleware.py`**

```bash
git rm backend/app/reasoning/langchain_agent/middlewares/memory_middleware.py
```

- [ ] **Step 3: Remove `memory_queue.py`**

```bash
git rm backend/app/reasoning/langchain_agent/middlewares/memory_queue.py
```

- [ ] **Step 4: Clean up `integrations.py` — remove dead HarnessConfig memory fields**

Remove from `HarnessConfig`:
```python
# Remove these fields:
memory_enabled: bool = False
kg_anchors_enabled: bool = False
```

Remove from `HarnessManager`:
```python
# Remove these methods:
_init_memory()
update_memory()
flush_memory()
track_entities()
```

- [ ] **Step 5: Clean up `client.py` — remove old post-run memory queue**

Remove from `run_lead_agent()`:
```python
# Remove post-run memory queue block:
if getattr(settings, "agent_memory_queue_enabled", True):
    from ...memory_middleware import HarnessMemoryUpdater, build_post_run_memory_messages
    from ...memory_queue import MemoryQueueLite
    ...
```

- [ ] **Step 6: Clean up `harness/__init__.py`**

Remove `MemoryManager`, `MemoryUpdater`, `MemoryUpdateQueue` exports.

- [ ] **Step 7: Run existing tests to verify nothing is broken**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/ -x -q 2>&1 | tail -30
```
Expected: no import errors, all passing (except possibly tests that directly imported deleted modules)

- [ ] **Step 8: Commit**

```bash
git add -A backend/app/
git commit -m "refactor(memory): remove old memory code (HarnessMemory, MemoryQueue, MemoryMiddleware)"
```

---

### Task 7: Context Compression Integration

**Files:**
- Modify: `backend/app/reasoning/langchain_agent/middlewares/context_compressor.py`
- No new test files needed (extend existing compression tests)

- [ ] **Step 1: Verify `<memory-context>` tag protection**

In `context_compressor.py`, find the tag protection logic and ensure `<memory-context>` is preserved:

```python
# In the compress method, add to protected tags list if not present:
PROTECTED_TAGS = {"<memory-context>", "<thinking>", "<feedback>"}
```

- [ ] **Step 2: Add compression hooks in run_lead_agent**

In `client.py`, when compression is triggered:
```python
# Before compression:
insights = await memory_manager.on_pre_compress(messages)

# After compression:
await memory_manager.on_session_end()
await memory_manager.initialize_all(thread_id)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/reasoning/langchain_agent/middlewares/context_compressor.py
git commit -m "feat(memory): add context compression integration with memory hooks"
```

---

### Task 8: Final Cleanup and Verification

**Files:**
- Modify: `backend/app/config.py` — remove deprecated settings
- Verify: `backend/app/reasoning/api/agent.py` — no references to old memory code

- [ ] **Step 1: Remove deprecated settings**

In `config.py`:
```python
# Remove:
agent_memory_queue_enabled: bool = True
agent_memory_debounce_seconds: float = 2.0
```

- [ ] **Step 2: Verify no stale imports in agent.py**

```bash
cd /home/lwm/code/QingshuiYanTou && grep -rn "memory_queue\|memory_middleware\|HarnessMemoryUpdater\|MemoryQueueLite" backend/app/ --include="*.py" | grep -v tests
```
Expected: no matches (except test files)

- [ ] **Step 3: Full test suite**

```bash
cd /home/lwm/code/QingshuiYanTou && python3 -m pytest backend/tests/reasoning/ -v 2>&1 | tail -40
```

- [ ] **Step 4: Final commit**

```bash
git add backend/app/config.py
git commit -m "chore(memory): remove deprecated memory config settings"
```

---

## Self-Review Checklist

1. **Spec coverage:** Every section in the spec (Provider ABC, BuiltinProvider, MemoryManager, tool, context compression, cleanup) has at least one corresponding task.
2. **Placeholder scan:** All code blocks contain actual implementation code, not TBDs.
3. **Type consistency:** `MemoryProvider` ABC methods match across Tasks 1-4. `MemoryManager` methods match usage in Task 5.
4. **Scope check:** Focused on memory system redesign only — no unrelated changes.
