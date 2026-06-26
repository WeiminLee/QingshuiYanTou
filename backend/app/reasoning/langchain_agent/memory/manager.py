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
