"""
test_sse_constants.py — Bug #4 复现测试

Bug #4: 工具截断阈值两处硬编码，SSE 数据一致性风险
  - tool_executor.py: SSE_MAX_LENGTH = 2000
  - client.py: result_str[:2000]  ← 曾硬编码，应集中到 tool_executor

现状：client.py 已重构，工具结果预览/截断集中到 tool_executor（build_preview /
truncate_for_sse），client 不再直接硬编码 2000。本测试改为验证该不变量。

Run: uv run --directory backend python -m pytest tests/reasoning/test_sse_constants.py -v
"""


class TestBug4SseTruncateConstant:
    """
    Bug #4 根因：SSE 截断阈值应集中在 tool_executor.SSE_MAX_LENGTH，
    client.py 不得再硬编码 2000。
    """

    def test_sse_max_length_defined_in_tool_executor(self):
        """截断常量集中定义于 tool_executor，值为 2000。"""
        from app.reasoning.langchain_agent.tool_executor import SSE_MAX_LENGTH

        assert SSE_MAX_LENGTH == 2000

    def test_client_uses_sse_max_length_constant(self):
        """
        Bug #4 修复验证：client.py 不再硬编码 result_str[:2000]（截断已集中到 tool_executor）。
        """
        import inspect

        from app.reasoning.langchain_agent import client as client_module

        source = inspect.getsource(client_module)

        # 修复后：不应有硬编码的 result_str[:2000]
        assert "result_str[:2000]" not in source, "client.py 不应硬编码 2000，应使用 tool_executor 的截断"
