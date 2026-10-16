"""退化终止检测器（backend/scripts/eval_degenerate_guard.py）的单元测试。

判别规则：`turn/end` 为 `completed` **且** 末条 assistant 消息既无 `text`
也无 `tool-call` 块 ⇒ 退化。这是 pjlab 网关在限流下返回截断补全却谎报
`stopReason: "stop"` 的形态（review_r1 / gap-wafer-margin-001 / session-38e06af1）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_degenerate_guard import ACTIONABLE_BLOCKS, classify  # noqa: E402


def _turn_end(kind: str) -> dict:
    return {"type": "turn/end", "data": {"turn": 1, "reason": {"kind": kind}}}


def _assistant(blocks: list[dict], step: int = 1) -> dict:
    return {"type": "assistant/message", "data": {"turn": 1, "step": step,
                                                  "message": {"role": "assistant", "content": blocks}}}


def test_reasoning_only_completed_turn_is_degenerate():
    events = [
        _assistant([{"type": "reasoning", "text": "现在并发发5个 metric_tre"}], step=7),
        _turn_end("completed"),
    ]
    degenerate, reason = classify(events)
    assert degenerate is True
    assert "no text and no tool call" in reason
    assert "step 7" in reason


def test_text_final_answer_is_healthy():
    events = [
        _assistant([{"type": "reasoning", "text": "think"}, {"type": "text", "text": "结论如下"}]),
        _turn_end("completed"),
    ]
    degenerate, _ = classify(events)
    assert degenerate is False


def test_tool_call_final_step_is_healthy():
    events = [
        _assistant([{"type": "reasoning", "text": "think"},
                    {"type": "tool-call", "id": "c1", "name": "compare_metric", "arguments": "{}"}]),
        _turn_end("completed"),
    ]
    degenerate, _ = classify(events)
    assert degenerate is False


def test_open_turn_is_not_counted():
    """仍在跑的案（无 turn/end）不得被判为退化，否则会误触发重跑。"""
    events = [_assistant([{"type": "reasoning", "text": "still working"}])]
    degenerate, reason = classify(events)
    assert degenerate is False
    assert "turn still open" in reason


def test_max_tokens_end_is_not_degenerate():
    """max-tokens 截断由框架另行处理（agent.ts 的 sticky max-tokens），不归本检测器。"""
    events = [_assistant([{"type": "reasoning", "text": "cut off"}]), _turn_end("max-tokens")]
    degenerate, reason = classify(events)
    assert degenerate is False
    assert "max-tokens" in reason


def test_completed_turn_without_any_assistant_message_is_degenerate():
    degenerate, reason = classify([_turn_end("completed")])
    assert degenerate is True
    assert "no assistant message" in reason


def test_actionable_blocks_constant_covers_text_and_tool_call():
    assert set(ACTIONABLE_BLOCKS) == {"text", "tool-call"}


def test_last_assistant_message_wins_not_the_first():
    """健康的首条不应掩盖退化的末条。"""
    events = [
        _assistant([{"type": "text", "text": "early note"}]),
        _assistant([{"type": "reasoning", "text": "truncated"}], step=7),
        _turn_end("completed"),
    ]
    degenerate, _ = classify(events)
    assert degenerate is True
