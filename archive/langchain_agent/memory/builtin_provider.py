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
            "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
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
            {"$set": {"profile": content, "updated_at": datetime.now(timezone.utc).isoformat()}},  # noqa: UP017
            upsert=True,
        )
        return {"success": True}

    def get_tool_schemas(self) -> list[dict[str, Any]]:
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
