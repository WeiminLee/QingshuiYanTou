"""UserMemoryProvider — 按 user_id 的 MongoDB 记忆（profile/preferences/notes）。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.reasoning.langchain_agent.memory.provider import MemoryProvider
from app.reasoning.langchain_agent.memory.text_utils import (
    jaccard_similarity,
    normalize_subject,
)
from app.reasoning.tools.guardrails import filter_research_memory_text

logger = logging.getLogger(__name__)

PROFILE_COLLECTION = "agent_profile"
NOTES_COLLECTION = "agent_notes"
PREF_COLLECTION = "agent_preferences"

MAX_PREFERENCES = 50
MAX_NOTES = 100
NOTE_DEDUP_THRESHOLD = 0.7
MAX_PREFETCH_TOKENS = 2000

STANCES = {"看好", "看空", "关注", "回避"}
SUBJECT_TYPES = {"sector", "concept", "stock"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def _get_collection(name: str):
    from app.core.mongodb import get_mongo_db

    return get_mongo_db()[name]


class UserMemoryProvider(MemoryProvider):
    def __init__(self):
        self._user_id: str | None = None

    @property
    def name(self) -> str:
        return "user_memory"

    def initialize(self, session_id: str) -> None:
        # MemoryManager.initialize_all 传入的是 user_id
        self._user_id = session_id
        logger.info("[UserMemoryProvider] initialized for user %s", session_id)

    def shutdown(self) -> None:
        self._user_id = None

    async def prefetch(self, query: str) -> str:  # 在 Task 5 实现
        return "<user-memory></user-memory>"

    async def sync_turn(self, user: str, assistant: str) -> None:
        # C 方案：留空接口。未来可在此实现每轮 LLM 偏好抽取。
        return None

    # ── profile ──
    async def set_profile(self, content: str) -> dict:
        await _get_collection(PROFILE_COLLECTION).update_one(
            {"user_id": self._user_id},
            {"$set": {"profile": content, "updated_at": _now()}},
            upsert=True,
        )
        return {"success": True}

    # ── preferences ──
    async def add_preference(self, subject: str, stance: str,
                             subject_type: str = "sector", reason: str = "") -> dict:
        subject_n = normalize_subject(subject)
        if not subject_n:
            return {"success": False, "error": "subject 为空"}
        if stance not in STANCES:
            return {"success": False, "error": f"非法 stance: {stance}"}
        if subject_type not in SUBJECT_TYPES:
            subject_type = "sector"
        doc = await _get_collection(PREF_COLLECTION).find_one({"user_id": self._user_id})
        items: list[dict] = (doc or {}).get("items", [])
        now = _now()
        for it in items:
            if normalize_subject(it.get("subject", "")) == subject_n:
                it.update({"stance": stance, "subject_type": subject_type,
                           "reason": reason or "", "updated_at": now})
                break
        else:
            items.append({"id": str(uuid.uuid4())[:8], "subject": subject_n,
                          "subject_type": subject_type, "stance": stance,
                          "reason": reason or "", "created_at": now, "updated_at": now})
        if len(items) > MAX_PREFERENCES:
            items.sort(key=lambda x: x.get("updated_at", ""))
            items = items[len(items) - MAX_PREFERENCES:]
        await _get_collection(PREF_COLLECTION).update_one(
            {"user_id": self._user_id}, {"$set": {"items": items}}, upsert=True)
        return {"success": True}

    async def remove_preference(self, subject: str) -> dict:
        subject_n = normalize_subject(subject)
        doc = await _get_collection(PREF_COLLECTION).find_one({"user_id": self._user_id})
        items: list[dict] = (doc or {}).get("items", [])
        new_items = [it for it in items
                     if normalize_subject(it.get("subject", "")) != subject_n]
        await _get_collection(PREF_COLLECTION).update_one(
            {"user_id": self._user_id}, {"$set": {"items": new_items}}, upsert=True)
        return {"success": len(new_items) < len(items)}

    # ── notes ──
    async def add_note(self, content: str, category: str = "general") -> dict:
        doc = await _get_collection(NOTES_COLLECTION).find_one({"user_id": self._user_id})
        entries: list[dict] = (doc or {}).get("entries", [])
        for e in entries:
            if jaccard_similarity(e.get("content", ""), content) > NOTE_DEDUP_THRESHOLD:
                return {"success": False, "skipped": True}
        entries.append({"id": str(uuid.uuid4())[:8], "content": content,
                        "category": category, "created_at": _now()})
        if len(entries) > MAX_NOTES:
            entries.sort(key=lambda x: x.get("created_at", ""))
            entries = entries[len(entries) - MAX_NOTES:]
        await _get_collection(NOTES_COLLECTION).update_one(
            {"user_id": self._user_id}, {"$set": {"entries": entries}}, upsert=True)
        return {"success": True, "skipped": False}

    async def replace_note(self, old_text: str, new_content: str) -> dict:
        r = await _get_collection(NOTES_COLLECTION).update_one(
            {"user_id": self._user_id, "entries.content": old_text},
            {"$set": {"entries.$.content": new_content}})
        return {"success": r.modified_count > 0}

    async def remove_note(self, old_text: str) -> dict:
        r = await _get_collection(NOTES_COLLECTION).update_one(
            {"user_id": self._user_id},
            {"$pull": {"entries": {"content": old_text}}})
        return {"success": r.modified_count > 0}

    # ── tool routing ──
    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [_MANAGE_MEMORY_SCHEMA]

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        if name != "manage_memory":
            return f"Unknown tool: {name}"
        if not self._user_id:
            return "Error: 记忆系统未初始化"
        action = args.get("action")
        target = args.get("target")
        content = args.get("content", "") or ""
        old_text = args.get("old_text")

        if content:
            if filter_research_memory_text(content) != content:
                return "Error: 内容包含不允许的指令，已拒绝写入。"

        if target == "profile":
            if action == "add":
                res = await self.set_profile(content)
            else:
                return "Error: profile 仅支持 add 操作"
        elif target == "preference":
            subject = args.get("subject", "")
            if action == "add":
                if filter_research_memory_text(subject) != subject:
                    return "Error: subject 包含不允许的指令，已拒绝写入。"
                res = await self.add_preference(
                    subject, args.get("stance", ""),
                    args.get("subject_type", "sector"), args.get("reason", ""))
            elif action == "remove":
                res = await self.remove_preference(subject)
            else:
                return "Error: preference 支持 add / remove"
        elif target == "notes":
            if action == "add":
                res = await self.add_note(content)
            elif action == "replace":
                if not old_text:
                    return "Error: replace 需要 old_text"
                res = await self.replace_note(old_text, content)
            elif action == "remove":
                if not old_text:
                    return "Error: remove 需要 old_text"
                res = await self.remove_note(old_text)
            else:
                return f"Error: 未知 action '{action}'"
        else:
            return f"Error: 未知 target '{target}'"

        if res.get("success"):
            return f"记忆已{action}。"
        if res.get("skipped"):
            return "已存在相似记忆，跳过。"
        if res.get("error"):
            return f"Error: {res['error']}"
        return "操作未生效（可能未找到匹配条目）。"


_MANAGE_MEMORY_SCHEMA: dict[str, Any] = {
    "name": "manage_memory",
    "description": (
        "管理用户长期记忆。preference：用户对某板块/概念/个股表达看好/看空/关注/回避时使用；"
        "profile：记录用户长期投资风格/风险偏好；notes：其他值得记住的信息。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "replace", "remove"]},
            "target": {"type": "string", "enum": ["notes", "profile", "preference"]},
            "content": {"type": "string", "description": "notes/profile 内容"},
            "old_text": {"type": "string", "description": "notes replace/remove 定位"},
            "subject": {"type": "string", "description": "preference 的板块/概念/个股名"},
            "stance": {"type": "string", "enum": ["看好", "看空", "关注", "回避"]},
            "subject_type": {"type": "string", "enum": ["sector", "concept", "stock"]},
            "reason": {"type": "string", "description": "preference 依据，可选"},
        },
        "required": ["action", "target"],
    },
}
