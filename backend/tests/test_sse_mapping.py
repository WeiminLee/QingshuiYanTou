"""
SSE 事件映射一致性测试
"""

import os
import re

import pytest


class TestSSEEventMapping:
    """测试 SSE 事件映射表一致性"""

    def test_event_mapping_consistency(self):
        """验证两处事件映射表一致性"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(os.path.join(base_dir, "app/reasoning/api/agent.py")) as f:
            code = f.read()

        # 提取 _VISIBLE_MAP 内容
        visible_map_match = re.search(r"_VISIBLE_MAP = \{(.+?)\n\}", code, re.DOTALL)
        event_map_match = re.search(r"event_map = \{(.+?)\n\}", code, re.DOTALL)

        if not visible_map_match or not event_map_match:
            pytest.skip("找不到映射表")

        visible_lines = [line.strip().rstrip(",") for line in visible_map_match.group(1).split("\n") if line.strip()]
        event_lines = [line.strip().rstrip(",") for line in event_map_match.group(1).split("\n") if line.strip()]

        # 提取 key: value 格式
        def extract_keys(lines):
            keys = set()
            for line in lines:
                if ":" in line:
                    key = line.split(":")[0].strip().strip('"').strip("'")
                    keys.add(key)
            return keys

        visible_keys = extract_keys(visible_lines)
        event_keys = extract_keys(event_lines)

        print(f"_VISIBLE_MAP 键: {visible_keys}")
        print(f"event_map 键: {event_keys}")

        # 检查差异
        only_in_visible = visible_keys - event_keys
        only_in_event = event_keys - visible_keys

        print(f"只在 _VISIBLE_MAP: {only_in_visible}")
        print(f"只在 event_map: {only_in_event}")

        if only_in_visible or only_in_event:
            pytest.fail(
                f"事件映射表不一致！\n"
                f"  只在 _VISIBLE_MAP: {only_in_visible}\n"
                f"  只在 event_map: {only_in_event}\n"
                "需要统一两处映射表"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
