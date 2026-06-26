"""
test_sse_constants.py — Bug #4 复现测试

Bug #4: 工具截断阈值两处硬编码，SSE 数据一致性风险
  - tool_executor.py: SSE_MAX_LENGTH = 2000
  - client.py: result_str[:2000]  ← 应引用 SSE_MAX_LENGTH

Run: uv run --directory backend python -m pytest tests/reasoning/test_sse_constants.py -v
"""


class TestBug4SseTruncateConstant:
    """
    Bug #4 根因：client.py:521 硬编码 2000，
    应引用 tool_executor.SSE_MAX_LENGTH。
    """

    def test_sse_max_length_imported_from_tool_executor(self):
        """
        Bug #4 修复验证：client.py 应从 tool_executor 导入 SSE_MAX_LENGTH。
        """
        from app.reasoning.langchain_agent.client import SSE_MAX_LENGTH as CLIENT_SSE_MAX_LENGTH
        from app.reasoning.langchain_agent.tool_executor import SSE_MAX_LENGTH

        assert SSE_MAX_LENGTH == CLIENT_SSE_MAX_LENGTH, (
            "client.py 应从 tool_executor 导入 SSE_MAX_LENGTH，确保两处截断值一致。"
        )
        assert SSE_MAX_LENGTH == 2000

    def test_client_uses_sse_max_length_constant(self):
        """
        Bug #4 修复验证：client.py 中的 SSE 截断使用 SSE_MAX_LENGTH 常量。
        """
        import inspect

        from app.reasoning.langchain_agent import client as client_module

        source = inspect.getsource(client_module)

        # 修复后：不应有硬编码的 result_str[:2000]
        assert "result_str[:2000]" not in source, "client.py 不应硬编码 2000，应使用 SSE_MAX_LENGTH 常量"
