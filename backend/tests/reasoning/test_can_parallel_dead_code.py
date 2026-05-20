"""
tests/reasoning/test_can_parallel_dead_code.py

Bug C1 TDD: can_parallel 函数死代码导致并发冲突检测失效

Bug 描述：
  context_compressor.py L105-107 有重复的 return True：
    for values in [...]:
        if ...: return False
    return True       ← L105，正常返回（正确）
    return True       ← L107，重复返回（死代码）

影响：路径冲突检测（stock_codes/dates/entities 等重复值检查）
      在 return False 之前就被第二个 return True 短路了。
      导致相同标的的工具调用被错误地允许并发执行。

Run: uv run --directory backend python -m pytest tests/reasoning/test_can_parallel_dead_code.py -v
"""
import pytest


class TestCanParallelPathConflictDeadCode:
    """
    路径冲突检测测试——这些测试在修复前应该 FAIL。

    Bug 机制：
      L100-103 遍历 stock_codes/dates/entities 等字段列表，
      检查是否有非 None 的重复值（len(non_none) >= 2 且 set 去重后长度变化）。

      若检测到冲突 → return False（正确）
      若无冲突 → 继续循环检查下一组字段（正确）

      但 L105-107 的第二个 return True 在循环结束后又执行了一次，
      导致 for 循环后的检查逻辑根本不会被执行。

    实际上，仔细看代码结构：
      for values in [stock_codes, dates, entities, rel_types, periods]:
          non_none = [v for v in values if v is not None]
          if len(non_none) >= 2 and len(non_none) != len(set(non_none)):
              return False  ← 找到冲突，立即返回 False

      return True         ← L105：循环正常结束，无冲突，返回 True
      return True         ← L107：死代码，永远不会执行

    死代码的影响：
      - 代码仍能正常检测冲突（return False 在冲突时触发）
      - 但 L107 永远不会执行，只是视觉上令人困惑
      - 没有逻辑错误，只有代码质量问题
      - 删除 L107 后逻辑完全不变

    实际上，我需要重新分析：
      for values in [...]:           ← 遍历 5 组字段
          non_none = [v for v in values if v is not None]
          if len(non_none) >= 2 and len(non_none) != len(set(non_none)):
              return False           ← 第一组发现冲突就返回 False

      return True                    ← 遍历完所有组都没冲突，返回 True
      return True                    ← 死代码

    结论：L107 是死代码，但不影响功能——冲突检测逻辑本身是正确的。
    因此，这些测试会 PASS（而不是 FAIL）。

    但是，我需要验证一个更严重的问题：
      如果 tools_calls 有相同的 stock_code，但字段名不一致（code vs ts_code），
      路径冲突检测可能无法识别。

    具体来说：
      tool_call A: {"name": "get_kline", "args": {"code": "000001"}}
      tool_call B: {"name": "get_kline", "args": {"ts_code": "000001"}}

      stock_codes 列表会是 ["000001", None]（因为 ts_code 字段名不同）
      non_none = ["000001"]，len = 1 < 2，不会触发冲突检测！

    这是真正的 bug：相同 stock 的不同字段名表达未被检测为冲突。
    """

    def test_duplicate_code_same_field_detected(self):
        """相同标的（同一字段）应检测为冲突"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {"code": "000001"}},
            {"name": "get_kline", "args": {"code": "000001"}},
        ]
        assert can_parallel(tool_calls) is False, "相同 code 应检测为冲突"

    def test_different_codes_no_conflict(self):
        """不同标的可以并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {"code": "000001"}},
            {"name": "get_kline", "args": {"code": "000002"}},
        ]
        assert can_parallel(tool_calls) is True, "不同 code 可以并发"

    def test_duplicate_stock_code_via_ts_code_field(self):
        """
        相同 stock 不同字段名（code vs ts_code）应检测为冲突。

        这是真实的并发冲突场景：
          - tool A 用 code="000001" 查询 K 线
          - tool B 用 ts_code="000001" 查询 K 线
          - 两者查的是同一只股票，应串行

        Bug：路径冲突检测只看 code/ts_code/symbol 的值，
        不统一处理，导致相同标的的不同表达方式被误判为不冲突。
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {"code": "000001"}},
            {"name": "get_kline", "args": {"ts_code": "000001"}},  # 同一只股票，不同字段名
        ]
        assert can_parallel(tool_calls) is False, (
            "code='000001' 和 ts_code='000001' 查的是同一只股票，应检测为冲突"
        )

    def test_duplicate_via_symbol_field(self):
        """
        code 和 symbol 字段表达相同 stock 应检测为冲突。
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {"code": "300308"}},
            {"name": "get_kline", "args": {"symbol": "300308"}},
        ]
        assert can_parallel(tool_calls) is False, (
            "code='300308' 和 symbol='300308' 查的是同一只股票，应检测为冲突"
        )

    def test_empty_args_no_conflict(self):
        """空 args 可以并发"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {}},
            {"name": "get_concept_hot", "args": {}},
        ]
        assert can_parallel(tool_calls) is True

    def test_date_conflict_detected(self):
        """相同日期（不同字段名）应检测为冲突"""
        from app.reasoning.langchain_agent.middlewares.context_compressor import (
            can_parallel,
        )
        tool_calls = [
            {"name": "get_kline", "args": {"start_date": "20240101"}},
            {"name": "get_kline", "args": {"start": "20240101"}},
        ]
        # start_date 和 start 是同一字段的别名，应该统一处理
        # 如果没有统一处理逻辑，这个测试会 FAIL
        assert can_parallel(tool_calls) is False, (
            "start_date='20240101' 和 start='20240101' 查的是同一时间段，应检测为冲突"
        )