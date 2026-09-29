"""
工具并发判断测试
"""

import os

import pytest


class TestToolConcurrency:
    """测试工具并发判断"""

    def test_safe_to_parallel_is_hardcoded(self):
        """验证 SAFE_TO_PARALLEL 是硬编码集合"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(os.path.join(base_dir, "app/reasoning/langchain_agent/tool_executor.py")) as f:
            code = f.read()

        # 检查 SAFE_TO_PARALLEL 是硬编码
        if "SAFE_TO_PARALLEL = frozenset({" in code:
            print("SAFE_TO_PARALLEL 是硬编码集合")
            # 列出包含的工具
            import re

            match = re.search(r"SAFE_TO_PARALLEL = frozenset\(\{(.+?)}\)", code, re.DOTALL)
            if match:
                tools = [t.strip().strip('"').strip("'") for t in match.group(1).split(",")]
                print(f"当前可并发工具: {tools}")
                print(f"总计: {len(tools)} 个工具")

                # 建议：应该有动态加载的机制
                pytest.skip("SAFE_TO_PARALLEL 是硬编码，建议改为从工具注册表动态加载")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
