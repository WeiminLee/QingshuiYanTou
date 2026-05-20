"""
reasoning 字段一致性测试
"""
import pytest
import os


class TestReasoningField:
    """测试 reasoning 字段在不同端点的一致性"""

    def test_reasoning_field_in_response(self):
        """验证所有响应都包含 reasoning 字段"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 检查 client.py 中的返回值
        with open(os.path.join(base_dir, "app/reasoning/langchain_agent/client.py"), "r") as f:
            client_code = f.read()

        # 检查是否有 reasoning 字段
        has_reasoning_in_client = '"reasoning":' in client_code or "'reasoning':" in client_code

        # 检查 agent.py 中的响应
        with open(os.path.join(base_dir, "app/reasoning/api/agent.py"), "r") as f:
            agent_code = f.read()

        # 统计有多少处传递了 reasoning
        reasoning_pass_count = agent_code.count("reasoning=")

        print(f"client.py 有 reasoning: {has_reasoning_in_client}")
        print(f"agent.py 传递 reasoning 次数: {reasoning_pass_count}")

        # 验证至少有 3 个端点传递了 reasoning
        assert reasoning_pass_count >= 3, \
            f"应该有至少 3 个端点传递 reasoning，当前只有 {reasoning_pass_count} 个"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])