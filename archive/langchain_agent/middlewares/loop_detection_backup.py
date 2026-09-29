"""
Loop Detection Middleware — AgentMiddleware 协议

检测 LLM 重复调用同一工具 + 相同参数的循环行为。
作为 create_agent 的 after_model 钩子注入。
"""

import hashlib
import json
import logging

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

DEFAULT_MAX_REPEATS = 3
DEFAULT_WINDOW_SIZE = 10


class LoopDetectionMiddleware(AgentMiddleware):
    """检测 ReAct 循环中的重复工具调用模式。"""

    name: str = "loop_detection"

    def __init__(
        self,
        max_repeats: int = DEFAULT_MAX_REPEATS,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ):
        super().__init__()
        self._max_repeats = max_repeats
        self._window_size = window_size

    @staticmethod
    def _tool_call_fingerprint(tool_call: dict) -> str:
        """生成工具调用的唯一指纹（tool_name + args hash）。"""
        tool_name = tool_call.get("name", "")
        args_str = json.dumps(tool_call.get("args", {}), sort_keys=True)
        args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
        return f"{tool_name}:{args_hash}"

    def after_model_hook(self, state: dict, response: AIMessage) -> AIMessage:
        """
        after_model 钩子：检查 AIMessage 中的 tool_calls 是否重复。

        如果同一指纹在窗口内出现 >= max_repeats 次，
        移除重复的 tool_calls 并添加提示让 LLM 换方向。
        """
        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            return response

        messages = state.get("messages", [])
        recent_messages = messages[-self._window_size :] if len(messages) > self._window_size else messages

        # 统计窗口内每个指纹出现次数
        fingerprint_counts: dict[str, int] = {}
        for msg in recent_messages:
            if isinstance(msg, AIMessage):
                for tc in getattr(msg, "tool_calls", []):
                    fp = self._tool_call_fingerprint(tc)
                    fingerprint_counts[fp] = fingerprint_counts.get(fp, 0) + 1

        # 检查当前 tool_calls 是否触发循环
        loop_detected = False
        filtered_tool_calls = []
        for tc in tool_calls:
            fp = self._tool_call_fingerprint(tc)
            if fingerprint_counts.get(fp, 0) >= self._max_repeats:
                loop_detected = True
                logger.warning(f"[LoopDetection] 循环检测触发: {fp} 已出现 {fingerprint_counts[fp]} 次")
            else:
                filtered_tool_calls.append(tc)

        if not loop_detected:
            return response

        # 循环检测触发：返回新 AIMessage，不修改原 response
        if filtered_tool_calls:
            return AIMessage(
                content=response.content,
                tool_calls=filtered_tool_calls,
                id=getattr(response, "id", None),
            )
        else:
            # 所有 tool_calls 都是重复的，强制 LLM 换方向
            return AIMessage(
                content="检测到重复工具调用循环。请换一个分析角度，"
                "使用不同的工具或参数，或者基于已有信息直接给出结论。",
                tool_calls=[],
                id=getattr(response, "id", None),
            )
