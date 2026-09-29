"""
Harness 集成模块

将 harness/ 中的核心能力（BudgetEnforcer、MemoryManager、KG Anchors）
集成到 LangChain Agent 引擎中。

Phase 1：创建接口框架，所有能力默认关闭，不影响现有逻辑。
Phase 2+：逐步接入具体实现。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── 配置 ────────────────────────────────────────────────────────────────────────


@dataclass
class HarnessConfig:
    """
    Harness 能力配置。

    所有能力默认关闭（向后兼容），
    在确认各能力稳定后再逐步开启。
    """

    budget_enabled: bool = False
    memory_enabled: bool = False
    kg_anchors_enabled: bool = False

    # Budget 参数（BudgetEnforcer）
    per_tool_cap: int = 50_000  # 单个工具结果上限（字符）
    per_turn_cap: int = 200_000  # 单轮总额上限（字符）
    preview_size: int = 1_500  # 截断预览 snippet 长度

    # Memory 参数（MemoryManager）
    debounce_seconds: float = 5.0  # 防抖窗口（秒）


# ── HarnessManager ────────────────────────────────────────────────────────────────


class HarnessManager:
    """
    统一管理三个 harness 能力的生命周期。

    Phase 1：仅创建实例，不启用任何能力。
    Phase 2+：接入 BudgetEnforcer、MemoryManager、KG Anchors。

    用法：
        config = HarnessConfig(budget_enabled=True)
        manager = HarnessManager(config, thread_id="xxx")

        # 在 agent.stream() 循环前
        manager.begin_turn()

        # 在 ToolMessage 处理后
        result_str = await manager.enforce_budget(tool_name, raw_result)

        # 在 agent.stream() 结束后
        manager.stop()
        summary = manager.get_summary()
    """

    def __init__(self, config: HarnessConfig, thread_id: str):
        self.config = config
        self.thread_id = thread_id
        self._budget_enforcer: Any = None
        self._memory_manager: Any = None
        self._kg_anchor_patterns: list[re.Pattern] | None = None

        # 惰性初始化各能力（仅在对应 enabled=True 时加载）
        if config.budget_enabled:
            self._init_budget()
        if config.memory_enabled:
            self._init_memory()
        if config.kg_anchors_enabled:
            self._init_kg_anchors()

    # ── 内部初始化 ─────────────────────────────────────────────────────────────

    def _init_budget(self) -> None:
        """惰性初始化 BudgetEnforcer"""
        try:
            from app.reasoning.harness.budget import BudgetConfig, BudgetEnforcer

            cfg = BudgetConfig(
                per_tool_cap=self.config.per_tool_cap,
                per_turn_cap=self.config.per_turn_cap,
                preview_size=self.config.preview_size,
                persist_enabled=True,
            )
            self._budget_enforcer = BudgetEnforcer(config=cfg)
            logger.info("[Harness] BudgetEnforcer initialized")
        except Exception as e:
            logger.warning(f"[Harness] BudgetEnforcer init failed: {e}, disabled")
            self._budget_enforcer = None

    def _init_memory(self) -> None:
        """惰性初始化 MemoryManager"""
        try:
            from app.reasoning.harness.memory import MemoryManager

            self._memory_manager = MemoryManager(
                debounce_seconds=self.config.debounce_seconds,
            )
            self._memory_manager.start()
            logger.info("[Harness] MemoryManager initialized")
        except Exception as e:
            logger.warning(f"[Harness] MemoryManager init failed: {e}, disabled")
            self._memory_manager = None

    def _init_kg_anchors(self) -> None:
        """惰性初始化 KG Anchors 实体识别模式"""
        # 复用 middlewares/graph.py 的已知公司名正则
        self._kg_anchor_patterns = _build_kg_patterns()
        logger.info(f"[Harness] KG Anchors initialized, {len(self._kg_anchor_patterns)} patterns")

    # ── Budget ───────────────────────────────────────────────────────────────

    def begin_turn(self, turn: int = 0) -> None:
        """开始新的一轮（BudgetEnforcer turn 边界）"""
        if self._budget_enforcer is not None:
            self._budget_enforcer.begin_turn(turn)

    def end_turn(self) -> None:
        """结束当前轮"""
        if self._budget_enforcer is not None:
            self._budget_enforcer.end_turn()

    async def enforce_budget(self, tool_name: str, raw_result: str) -> str:
        """
        对工具结果执行 Budget 三层防御。

        如果 BudgetEnforcer 未启用，直接返回原文本。
        """
        if self._budget_enforcer is None:
            return raw_result
        try:
            budgeted = await self._budget_enforcer.enforce(
                tool_name=tool_name,
                raw_result=raw_result,
                thread_id=self.thread_id,
            )
            return budgeted.truncated
        except Exception as e:
            logger.warning(f"[Harness] enforce_budget failed: {e}")
            return raw_result

    # ── Memory ───────────────────────────────────────────────────────────────

    def update_memory(self, messages: list[dict]) -> None:
        """
        触发记忆更新（有防抖，不阻塞主流程）。
        """
        if self._memory_manager is None:
            return
        try:
            self._memory_manager.update(
                thread_id=self.thread_id,
                agent_name=None,
                messages=messages,
            )
        except Exception as e:
            logger.warning(f"[Harness] update_memory failed: {e}")

    def flush_memory(self) -> None:
        """强制刷新 MemoryManager 队列（session 结束时调用）"""
        if self._memory_manager is not None:
            try:
                self._memory_manager.flush()
            except Exception as e:
                logger.warning(f"[Harness] flush_memory failed: {e}")

    # ── KG Anchors ──────────────────────────────────────────────────────────

    def track_entities(self, text: str) -> None:
        """
        追踪文本中的实体提及，调用 increment_kg_anchor。
        """
        if self._kg_anchor_patterns is None:
            return
        try:
            _do_track_entities(text, self.thread_id, self._kg_anchor_patterns)
        except Exception as e:
            logger.warning(f"[Harness] track_entities failed: {e}")

    # ── 生命周期 ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """
        停止所有活跃能力：
        - 刷新 MemoryManager 队列
        - 结束 BudgetEnforcer 当前轮
        """
        self.flush_memory()
        self.end_turn()
        logger.info(f"[Harness] stopped for thread={self.thread_id}")

    def get_summary(self) -> dict:
        """返回各能力的统计摘要"""
        summary: dict[str, Any] = {}
        if self._budget_enforcer is not None:
            summary["budget"] = self._budget_enforcer.get_summary()
        if self._memory_manager is not None:
            # MemoryManager 目前没有 get_summary，预留接口
            summary["memory"] = {"enabled": True}
        return summary


# ── KG 实体识别 ────────────────────────────────────────────────────────────────


# 常见上市公司正则（6位代码 + 交易所后缀）
_STOCK_PATTERN = re.compile(r"\b(\d{6})\.(SH|SZ|BJ)\b")
# 产品/技术词（追加识别）
_PRODUCT_PATTERNS = [
    re.compile(rf"\b{kw}\b")
    for kw in [
        "光模块",
        "光通信",
        "激光雷达",
        "CPO",
        "硅光",
        "光伏",
        "锂电",
        "储能",
        "功率半导体",
        "碳化硅",
        "AI芯片",
        "GPU",
        "HBM",
        "先进封装",
        "机器人",
        "减速器",
        "控制器",
        "传感器",
    ]
]


def _build_kg_patterns() -> list[re.Pattern]:
    """构建 KG Anchors 实体识别正则模式"""
    return [_STOCK_PATTERN] + _PRODUCT_PATTERNS


def _do_track_entities(text: str, thread_id: str, patterns: list[re.Pattern]) -> None:
    """
    同步后台追踪实体（在新线程中执行，避免阻塞）。
    复用 harness/memory.py 的 increment_kg_anchor。
    """
    import threading

    def _worker():
        try:
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_track_async(text, thread_id, patterns))
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"[KGAnchors] track worker failed: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


async def _track_async(text: str, thread_id: str, patterns: list[re.Pattern]) -> None:
    """异步追踪实体"""
    try:
        from app.reasoning.harness.memory import increment_kg_anchor

        # 股票代码
        for match in _STOCK_PATTERN.finditer(text):
            code = match.group(1)
            exchange = match.group(2)
            entity_name = f"{code}.{exchange}"
            await increment_kg_anchor(
                thread_id=thread_id,
                entity_id=entity_name,
                entity_name=entity_name,
                entity_type="Company",
            )

        # 产品/技术词
        for pattern in _PRODUCT_PATTERNS:
            for match in pattern.finditer(text):
                kw = match.group(0)
                await increment_kg_anchor(
                    thread_id=thread_id,
                    entity_id=kw,
                    entity_name=kw,
                    entity_type="Product",
                )
    except Exception as e:
        logger.warning(f"[KGAnchors] _track_async failed: {e}")


def format_kg_anchors(thread_id: str) -> str:
    """
    格式化 KG Anchors 列表，用于注入 System Prompt。

    复用 harness/memory.py 的 format_kg_anchors_for_prompt。
    """
    try:
        from app.reasoning.harness.memory import format_kg_anchors_for_prompt

        return format_kg_anchors_for_prompt(thread_id)
    except Exception as e:
        logger.warning(f"[Harness] format_kg_anchors failed: {e}")
        return ""
