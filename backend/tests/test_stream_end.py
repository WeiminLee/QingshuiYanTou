"""
Agent 事件流测试
检测 stream_end 重复发射问题
"""

import os

import pytest


class TestSSEEventEmission:
    """测试 SSE 事件发射，验证无重复"""

    def test_stream_end_should_not_duplicate(self):
        """
        验证 stream_end 事件只发射一次

        问题：
        - ManualAgentLoop.run() 会发射 stream_end
        - _run_stream_report() 也会发射 stream_end
        -> 导致重复
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 检查 ManualAgentLoop.run() 中的 stream_end 发射
        loop_file = os.path.join(base_dir, "app/reasoning/langchain_agent/middlewares/manual_agent_loop.py")
        with open(loop_file) as f:
            loop_code = f.read()

        # 检查 agent.py 中的 stream_end 发射
        agent_file = os.path.join(base_dir, "app/reasoning/api/agent.py")
        with open(agent_file) as f:
            agent_code = f.read()

        # 查找 stream_end 发射位置
        loop_stream_end = 'emit_fn("stream_end"' in loop_code
        agent_stream_end = 'type="stream_end"' in agent_code

        print(f"ManualAgentLoop 发射 stream_end: {loop_stream_end}")
        print(f"_run_stream_report 发射 stream_end: {agent_stream_end}")

        # 两者都发射就会重复
        if loop_stream_end and agent_stream_end:
            pytest.fail(
                "stream_end 重复发射！\n"
                f"  - ManualAgentLoop.run() 发射: {loop_stream_end}\n"
                f"  - _run_stream_report() 发射: {agent_stream_end}\n"
                "修复：移除 _run_stream_report 中的 stream_end 发射，"
                "因为 ManualAgentLoop.run() 已经发射"
            )

    def test_stream_end_data_structure(self):
        """验证 stream_end 数据结构一致性"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        loop_file = os.path.join(base_dir, "app/reasoning/langchain_agent/middlewares/manual_agent_loop.py")
        with open(loop_file) as f:
            loop_code = f.read()

        with open(os.path.join(base_dir, "app/reasoning/api/agent.py")) as f:
            agent_code = f.read()

        # 提取两个地方的 stream_end 数据字段
        # ManualAgentLoop 发射的数据
        loop_has_content = '"content": raw_analysis' in loop_code
        # _run_stream_report 发射的数据
        agent_has_content = '"content"' in agent_code and "stream_end" in agent_code

        print(f"ManualAgentLoop 有 content 字段: {loop_has_content}")
        print(f"_run_stream_report 有 content 字段: {agent_has_content}")
