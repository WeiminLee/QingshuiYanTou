"""
TokenUsageMiddleware — Token 消耗追踪中间件

记录每个模型调用的 token 消耗：
- prompt tokens (输入)
- completion tokens (输出)
- total tokens

作为 create_agent 的 after_model 钩子注入。

用途：
1. 成本追踪：累计每个会话的 token 消耗
2. 调试：识别异常的 token 使用模式
3. 配额管理：触发告警当 token 使用超过阈值
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# Token 消耗告警阈值（用于超过时记录 WARNING）
_TOKEN_ALERT_THRESHOLD = 50000  # 单次调用超过 50k tokens 告警


@dataclass
class TokenUsage:
    """单次模型调用的 token 统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionTokenStats:
    """会话级别的累计 token 统计。"""
    thread_id: str
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    first_call_time: float = field(default_factory=time.time)
    last_call_time: float = field(default_factory=time.time)

    @property
    def avg_tokens_per_call(self) -> float:
        """平均每次调用的 token 数。"""
        if self.call_count == 0:
            return 0.0
        return self.total_tokens / self.call_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "avg_tokens_per_call": round(self.avg_tokens_per_call, 1),
            "elapsed_seconds": round(self.last_call_time - self.first_call_time, 1),
        }


class TokenUsageMiddleware(AgentMiddleware):
    """
    Token 消耗追踪中间件。

    功能：
    1. 从 model_response 提取 usage metadata
    2. 累计会话级 token 消耗
    3. 超过阈值时记录 WARNING
    4. 提供 get_session_stats() 查询接口

    用法（client.py）：
        token_mw = TokenUsageMiddleware()
        # stream 循环中使用
    """

    name: str = "token_usage"

    def __init__(
        self,
        alert_threshold: int = _TOKEN_ALERT_THRESHOLD,
        max_tracked_sessions: int = 500,
    ):
        super().__init__()
        self._alert_threshold = alert_threshold
        self._max_tracked = max_tracked_sessions
        self._lock = threading.Lock()
        # thread_id -> SessionTokenStats
        self._session_stats: dict[str, SessionTokenStats] = {}

    def _get_or_create_stats(self, thread_id: str) -> SessionTokenStats:
        """获取或创建会话统计对象。"""
        with self._lock:
            if thread_id not in self._session_stats:
                # 驱逐过多会话
                if len(self._session_stats) >= self._max_tracked:
                    oldest = min(
                        self._session_stats.keys(),
                        key=lambda tid: self._session_stats[tid].last_call_time,
                    )
                    self._session_stats.pop(oldest, None)
                self._session_stats[thread_id] = SessionTokenStats(thread_id=thread_id)
            return self._session_stats[thread_id]

    def _extract_usage(self, response: AIMessage) -> TokenUsage | None:
        """从 AIMessage 响应中提取 token 使用量。"""
        # 尝试从 response_metadata 中获取
        metadata = getattr(response, "response_metadata", {}) or {}
        usage = metadata.get("usage") or {}

        # 直接属性
        if not usage:
            usage = getattr(response, "usage", None) or {}

        if isinstance(usage, dict):
            return TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0) or usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0) or usage.get("total_tokens", 0),
                model=getattr(response, "model_name", "") or metadata.get("model", ""),
            )

        # 如果 usage 是一个对象（有 .prompt_tokens 属性）
        if hasattr(usage, "prompt_tokens"):
            return TokenUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0),
                completion_tokens=getattr(usage, "completion_tokens", 0),
                total_tokens=getattr(usage, "total_tokens", 0),
                model=getattr(response, "model_name", "") or metadata.get("model", ""),
            )

        return None

    def after_model_hook(self, state: dict, response: AIMessage) -> AIMessage:
        """after_model 钩子：记录 token 消耗。"""
        thread_id = state.get("configurable", {}).get("thread_id", "default")

        usage = self._extract_usage(response)
        if not usage:
            logger.debug("[TokenUsage] 无法从响应中提取 usage metadata")
            return response

        # 更新会话统计
        stats = self._get_or_create_stats(thread_id)
        with self._lock:
            stats.total_prompt_tokens += usage.prompt_tokens
            stats.total_completion_tokens += usage.completion_tokens
            stats.total_tokens += usage.total_tokens
            stats.call_count += 1
            stats.last_call_time = time.time()

        # 告警：单次调用 token 超阈值
        if usage.total_tokens > self._alert_threshold:
            logger.warning(
                "[TokenUsage] 单次调用 token 超阈值: thread=%s tokens=%d threshold=%d",
                thread_id,
                usage.total_tokens,
                self._alert_threshold,
            )

        # DEBUG 日志（每 N 次打一次，避免日志过多）
        if stats.call_count % 20 == 0 or usage.total_tokens > self._alert_threshold:
            logger.info(
                "[TokenUsage] 累计统计: thread=%s calls=%d total=%d prompt=%d completion=%d",
                thread_id,
                stats.call_count,
                stats.total_tokens,
                stats.total_prompt_tokens,
                stats.total_completion_tokens,
            )

        return response

    def get_session_stats(self, thread_id: str) -> dict[str, Any] | None:
        """获取会话级 token 统计。"""
        with self._lock:
            if thread_id not in self._session_stats:
                return None
            return self._session_stats[thread_id].to_dict()

    def get_all_stats(self) -> list[dict[str, Any]]:
        """获取所有会话的 token 统计（用于调试）。"""
        with self._lock:
            return [s.to_dict() for s in self._session_stats.values()]

    def reset_session(self, thread_id: str | None = None) -> None:
        """清理会话统计。"""
        with self._lock:
            if thread_id:
                self._session_stats.pop(thread_id, None)
            else:
                self._session_stats.clear()

    def get_total_cost_estimate(
        self,
        prompt_price_per_1m: float = 0.5,
        completion_price_per_1m: float = 1.5,
    ) -> dict[str, float]:
        """
        估算所有会话的总成本（基于配置的价格）。

        Args:
            prompt_price_per_1m: 每百万 prompt tokens 的价格（美元）
            completion_price_per_1m: 每百万 completion tokens 的价格（美元）

        Returns:
            {"total_cost": float, "prompt_cost": float, "completion_cost": float}
        """
        with self._lock:
            total_prompt = sum(s.total_prompt_tokens for s in self._session_stats.values())
            total_completion = sum(s.total_completion_tokens for s in self._session_stats.values())

        prompt_cost = (total_prompt / 1_000_000) * prompt_price_per_1m
        completion_cost = (total_completion / 1_000_000) * completion_price_per_1m

        return {
            "total_cost": prompt_cost + completion_cost,
            "prompt_cost": prompt_cost,
            "completion_cost": completion_cost,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
        }