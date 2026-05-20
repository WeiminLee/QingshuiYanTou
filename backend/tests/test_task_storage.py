"""
任务存储管理测试
验证 _task_store 和 _task_manager 统一问题
"""
import pytest
import os


class TestTaskStorage:
    """测试任务存储双重管理问题"""

    def test_task_store_duplication(self):
        """验证 _task_store 和 _task_manager 并存问题"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        agent_file = os.path.join(base_dir, "app/reasoning/api/agent.py")
        with open(agent_file, "r") as f:
            code = f.read()

        # 检查是否有双重存储
        has_task_store = "_task_store: dict" in code
        has_task_manager = "_task_manager" in code

        print(f"有 _task_store: {has_task_store}")
        print(f"有 _task_manager: {has_task_manager}")

        # 检查是否同时写入两处
        task_store_write = "_task_store[task_id]" in code
        task_manager_set_result = "set_result" in code

        print(f"写入 _task_store: {task_store_write}")
        print(f"使用 set_result: {task_manager_set_result}")

        # 如果两处都写入，说明有重复
        if task_store_write and task_manager_set_result:
            # 检查是否在同一个函数中
            if "_run_invoke_task" in code and "_run_stream_report" in code:
                pytest.fail(
                    "任务存储双重管理！\n"
                    "  - _run_invoke_task 写入 _task_store\n"
                    "  - _run_stream_report 使用 _task_manager.set_result\n"
                    "修复：统一使用 _task_manager，移除 _task_store 写入"
                )

    def test_task_store_read_duplication(self):
        """验证读取时也查两处的问题"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        agent_file = os.path.join(base_dir, "app/reasoning/api/agent.py")
        with open(agent_file, "r") as f:
            code = f.read()

        # 检查是否在 /result 端点同时查两处
        # 查找 get_task_result 函数
        has_dual_read = "_task_store.get(task_id)" in code and "_task_manager.get_result" in code

        print(f"读取时查两处: {has_dual_read}")

        if has_dual_read:
            # 这是遗留问题，应该统一查 _task_manager
            print("提示: /result 端点应该统一使用 _task_manager.get_result")