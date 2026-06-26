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
