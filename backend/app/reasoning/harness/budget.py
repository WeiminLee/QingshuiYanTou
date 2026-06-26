"""
BudgetEnforcer — 三层 Budget 防御

参考 HermesAgentLoop 的 BudgetEnforcer 设计：
  Layer 1: per-tool result cap      — 单个工具结果上限
  Layer 2: per-turn aggregate       — 单轮所有工具结果总额
  Layer 3: preview truncation        — 超限截断为 preview snippet + 存储指针

用途：
  - 防止单个工具返回过多数据导致 token 爆炸
  - 防止一轮内所有工具结果堆积超限
  - 提供持久化存储大结果的机制（结果存储到 MongoDB，prompt 中只返回指针）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

DEFAULT_PER_TOOL_CAP = 50_000  # 单个工具结果上限（字符）
DEFAULT_PER_TURN_CAP = 200_000  # 单轮总额上限（字符）
DEFAULT_PREVIEW_SIZE = 1_500  # 截断预览 snippet 长度
DEFAULT_STORAGE_COLLECTION = "harness_tool_results"


@dataclass
class ToolResultBudget:
    """单个工具的结果预算记录"""

    tool_name: str
    char_count: int
    original: str
    truncated: str = ""  # 截断后的预览文本
    persisted_key: str = ""  # 持久化存储 key（超限大结果时）
    was_truncated: bool = False


@dataclass
class TurnBudget:
    """单轮预算状态"""

    turn: int
    turn_cap: int = DEFAULT_PER_TURN_CAP
    total_chars: int = 0
    tool_results: list[ToolResultBudget] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.turn_cap - self.total_chars)

    def can_add(self, tool_name: str, result_len: int) -> bool:
        return self.total_chars + result_len <= self.turn_cap


@dataclass
class BudgetConfig:
    """Budget 配置"""

    per_tool_cap: int = DEFAULT_PER_TOOL_CAP
    per_turn_cap: int = DEFAULT_PER_TURN_CAP
    preview_size: int = DEFAULT_PREVIEW_SIZE
    # 持久化配置（MongoDB 存储大结果，prompt 只返回指针）
    persist_enabled: bool = True
    persist_collection: str = DEFAULT_STORAGE_COLLECTION


# ── 持久化存储 ────────────────────────────────────────────────────────────────


async def _persist_result(key: str, content: str, thread_id: str) -> str:
    """
    将超限结果持久化到 MongoDB。
    返回存储 key，prompt 中仅返回 "（结果已存储，key={key}）"
    """
    try:
        from datetime import datetime

        from app.core.mongodb import get_mongo_db

        db = get_mongo_db()
        col = db[DEFAULT_STORAGE_COLLECTION]

        await col.update_one(
            {"key": key},
            {
                "$set": {
                    "content": content,
                    "thread_id": thread_id,
                    "updated_at": datetime.now(),
                }
            },
            upsert=True,
        )
        logger.debug(f"[Budget] Persisted result: key={key}, size={len(content)}")
        return key
    except Exception as e:
        logger.warning(f"[Budget] Persist failed: {e}")
        return ""


async def _load_persisted_result(key: str) -> str:
    """从 MongoDB 加载持久化结果"""
    try:
        from app.core.mongodb import get_mongo_db

        db = get_mongo_db()
        col = db[DEFAULT_STORAGE_COLLECTION]
        doc = await col.find_one({"key": key})
        return doc["content"] if doc else "[结果已过期]"
    except Exception as e:
        logger.warning(f"[Budget] Load persisted result failed: {e}")
        return "[结果加载失败]"


# ── BudgetEnforcer ─────────────────────────────────────────────────────────────


class BudgetEnforcer:
    """
    三层 Budget 防御。

    Layer 1 — per-tool cap：单个工具结果超过 per_tool_cap 时截断
    Layer 2 — per-turn aggregate：单轮总字符超过 per_turn_cap 时触发持久化
    Layer 3 — preview truncation：超限大结果写入 MongoDB，prompt 只返回指针

    用法：
        enforcer = BudgetEnforcer(config=BudgetConfig())
        async for result in tool_call_stream:
            budgeted = await enforcer.enforce(tool_name, result, thread_id="xxx")
    """

    def __init__(self, config: BudgetConfig | None = None):
        self.config = config or BudgetConfig()
        self._current_turn: TurnBudget | None = None
        self._turn_history: list[TurnBudget] = []
        self._persisted_keys: dict[str, str] = {}  # key → thread_id

    # ── Turn 管理 ─────────────────────────────────────────────────────────────

    def begin_turn(self, turn: int) -> None:
        """开始新的一轮（每轮开始时调用）"""
        self._current_turn = TurnBudget(turn=turn, turn_cap=self.config.per_turn_cap)
        logger.debug(f"[Budget] Begin turn {turn}, cap={self.config.per_turn_cap}")

    def end_turn(self) -> TurnBudget | None:
        """结束当前轮"""
        if self._current_turn is not None:
            self._turn_history.append(self._current_turn)
        self._current_turn = None
        return self._turn_history[-1] if self._turn_history else None

    @property
    def current_turn(self) -> TurnBudget | None:
        return self._current_turn

    @property
    def turns_used(self) -> int:
        return len(self._turn_history)

    # ── 核心 enforce ───────────────────────────────────────────────────────

    async def enforce(
        self,
        tool_name: str,
        raw_result: str,
        thread_id: str = "",
    ) -> ToolResultBudget:
        """
        对工具结果执行三层 Budget 防御。

        Returns ToolResultBudget，其中：
          .original   — 原始结果（未截断）
          .truncated — 截断后返回给 LLM 的文本
          .was_truncated — 是否发生了截断
          .persisted_key — 如果超限大结果被持久化，返回存储 key
        """
        char_count = len(raw_result)
        budget = ToolResultBudget(
            tool_name=tool_name,
            char_count=char_count,
            original=raw_result,
        )

        # ── Layer 1: per-tool cap ──────────────────────────────────────
        if char_count > self.config.per_tool_cap:
            truncated = raw_result[: self.config.per_tool_cap]
            budget.truncated = truncated
            budget.was_truncated = True
            logger.info(
                f"[Budget] Layer1 per-tool cap hit: {tool_name} ({char_count} → {self.config.per_tool_cap} chars)"
            )
        else:
            budget.truncated = raw_result

        # ── Layer 2: per-turn aggregate ────────────────────────────────
        if self._current_turn is None:
            # 未调用 begin_turn，直接返回 Layer1 结果
            return budget

        if not self._current_turn.can_add(tool_name, len(budget.truncated)):
            # Layer 2 超限：持久化并返回指针
            if self.config.persist_enabled and thread_id:
                key = f"{thread_id}/{tool_name}/{self._current_turn.turn}"
                stored_key = await _persist_result(key, raw_result, thread_id)
                if stored_key:
                    budget.persisted_key = stored_key
                    budget.truncated = (
                        f"【结果已存储（{char_count} chars），key={stored_key}，"
                        f'如需完整结果请调用 tool_result(key="{stored_key}")】'
                    )
                    budget.was_truncated = True
                    logger.info(
                        f"[Budget] Layer2 per-turn cap hit: {tool_name} "
                        f"(turn={self._current_turn.turn}, total={self._current_turn.total_chars})"
                    )
            else:
                # 持久化不可用，强制 Layer1 截断
                budget.truncated = budget.truncated[: self.config.per_turn_cap - self._current_turn.total_chars]
                budget.was_truncated = True
        else:
            # 正常追加到当前轮总额
            self._current_turn.total_chars += len(budget.truncated)

        self._current_turn.tool_results.append(budget)
        return budget

    # ── 便捷同步方法 ──────────────────────────────────────────────────────

    def enforce_sync(self, tool_name: str, raw_result: str) -> str:
        """
        同步版本（不持久化，不追踪 turn）。
        用于对已存储的大结果做快速截断。
        """
        if len(raw_result) <= self.config.per_tool_cap:
            return raw_result
        return raw_result[: self.config.per_tool_cap]

    def get_summary(self) -> dict:
        """返回 Budget 统计摘要（用于日志/报告）"""
        if not self._turn_history:
            return {"turns": 0, "total_chars": 0, "truncated_tools": 0}

        truncated = sum(1 for tb in self._turn_history for r in tb.tool_results if r.was_truncated)
        return {
            "turns": len(self._turn_history),
            "total_chars": sum(tb.total_chars for tb in self._turn_history),
            "truncated_tools": truncated,
            "persisted_keys": sum(1 for tb in self._turn_history for r in tb.tool_results if r.persisted_key),
        }
